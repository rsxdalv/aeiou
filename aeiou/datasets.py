# AUTOGENERATED! DO NOT EDIT! File to edit: ../01_datasets.ipynb.

# %% auto 0
__all__ = ['PadCrop', 'PhaseFlipper', 'FillTheNoise', 'RandPool', 'NormInputs', 'Mono', 'Stereo', 'RandomGain', 'AudioDataset']

# %% ../01_datasets.ipynb 4
import torch
import torch.nn as nn
import torchaudio
from torchaudio import transforms as T
import random
import os
import tqdm
from multiprocessing import Pool, cpu_count
from functools import partial
from .core import load_audio, get_audio_filenames

# %% ../01_datasets.ipynb 6
class PadCrop(nn.Module):
    def __init__(self, n_samples, randomize=True):
        super().__init__()
        self.n_samples = n_samples
        self.randomize = randomize

    def __call__(self, signal):
        n, s = signal.shape
        start = 0 if (not self.randomize) else torch.randint(0, max(0, s - self.n_samples) + 1, []).item()
        end = start + self.n_samples
        output = signal.new_zeros([n, self.n_samples])
        output[:, :min(s, self.n_samples)] = signal[:, start:end]
        return output

    
class PhaseFlipper(nn.Module):
    "she was PHAAAAAAA-AAAASE FLIPPER, a random invert yeah"
    def __init__(self, p=0.5):
        super().__init__()
        self.p = p
    def __call__(self, signal):
        return -signal if (random.random() < self.p) else signal


class FillTheNoise(nn.Module):
    "randomly adds a bit of noise, just to spice things up"
    def __init__(self, p=0.33):
        super().__init__()
        self.p = p
    def __call__(self, signal):
        return signal + 0.25*random.random()*(2*torch.rand_like(signal)-1) if (random.random() < self.p) else signal

    
class RandPool(nn.Module):
    def __init__(self, p=0.2):
        self.p, self.maxkern = p, 100
    def __call__(self, signal):
        if (random.random() < self.p):
            ksize = int(random.random()*self.maxkern)
            avger = nn.AvgPool1d(kernel_size=ksize, stride=1, padding=1)
            return avger(signal)
        else:
            return signal
        

class NormInputs(nn.Module):
    "useful for quiet inputs. intended to be part of augmentation chain; not activated by default"
    def __init__(self, do_norm=False):
        super().__init__()
        self.do_norm = do_norm
        self.eps = 1e-2
    def __call__(self, signal):
        return signal if (not self.do_norm) else signal/(torch.amax(signal,-1)[0] + self.eps)

    
class Mono(nn.Module):
    def __call__(self, signal):
        return torch.mean(signal, dim=0) if len(signal.shape) > 1 else signal


class Stereo(nn.Module):

    def __call__(self, signal):
        signal_shape = signal.shape
        # Check if it's mono
        if len(signal_shape) == 1: # s -> 2, s
            signal = signal.unsqueeze(0).repeat(2, 1)
        elif len(signal_shape) == 2:
            if signal_shape[0] == 1: #1, s -> 2, s
                signal = signal.repeat(2, 1)
            elif signal_shape[0] > 2: #?, s -> 2,s
                signal = signal[:2, :]    
        return signal

    
class RandomGain(nn.Module):
    def __init__(self, min_gain, max_gain):
        super().__init__()
        self.min_gain = min_gain
        self.max_gain = max_gain

    def __call__(self, signal):
        gain = random.uniform(self.min_gain, self.max_gain)
        signal = signal * gain
        return signal

# %% ../01_datasets.ipynb 8
class AudioDataset(torch.utils.data.Dataset):
  """
  Reads from a tree of directories and serves up cropped bits from any and all audio files
  found therein. For efficiency, best if you "chunk" these files via chunkadelic
  modified from https://github.com/drscotthawley/audio-diffusion/blob/main/dataset/dataset.py
  """
  def __init__(self, 
    paths, 
    sample_rate=48000, 
    sample_size=65536, 
    random_crop=True, 
    load_frac=1.0, 
    cache_training_data=False, 
    num_gpus=8,
    augs='PadCrop(sample_size), PhaseFlipper()'              # list of augmentation transforms, as a string
    ):

    super().__init__()
    self.filenames = []
    print(f"type(augs) = {type(augs)}")
    #self.augs = torch.nn.Sequential( eval(augs) )
    self.augs = torch.nn.Sequential(
      PadCrop(sample_size, randomize=random_crop),
      #RandomGain(0.7, 1.0),
      #RandPool(),
      #FillTheNoise(),
      PhaseFlipper(),
      #NormInputs(do_norm=global_args.norm_inputs),
    )

    self.encoding = torch.nn.Sequential(
      #Stereo()       # if images can be 3-channel RGB, we can do stereo. 
      Mono()   # but RAVE expects mono, ....for now ;-) 
    )

    self.filenames = get_audio_file_list(paths)
    print(f"{len(self.filenames)} files found.")

    self.sr = sample_rate
    self.load_frac = load_frac
    self.n_files = int(len(self.filenames)*self.load_frac)
    self.filenames = self.filenames[0:self.n_files]
    self.num_gpus = num_gpus
    self.cache_training_data = cache_training_data

    if self.cache_training_data: self.preload_files()

    self.convert_tensor = VT.ToTensor()

  def load_file(self, filename):
    audio, sr = torchaudio.load(filename)
    if sr != self.sr:
      resample_tf = T.Resample(sr, self.sr)
      audio = resample_tf(audio)
    return audio

  def load_file_ind(self, file_list,i): # used when caching training data
    return self.load_file(file_list[i]).cpu()

  def get_data_range(self): # for parallel runs, only grab part of the data -- OBVIATED BY CHUNKING.
    start, stop = 0, len(self.filenames)
    try:
      local_rank = int(os.environ["LOCAL_RANK"])
      world_size = int(os.environ["WORLD_SIZE"])
      interval = stop//world_size
      start, stop = local_rank*interval, (local_rank+1)*interval
      return start, stop
    except KeyError as e: # we're on GPU 0 and the others haven't been initialized yet
      start, stop = 0, len(self.filenames)//self.num_gpus
      return start, stop

  def preload_files(self):
      print(f"Caching {self.n_files} input audio files:")
      wrapper = partial(self.load_file_ind, self.filenames)
      start, stop = self.get_data_range()
      with Pool(processes=cpu_count()) as p:   # //8 to avoid FS bottleneck and/or too many processes (b/c * num_gpus)
        self.audio_files = list(tqdm.tqdm(p.imap(wrapper, range(start,stop)), total=stop-start))

  def __len__(self):
    return len(self.filenames)

  def __getitem__(self, idx):
    audio_filename = self.filenames[idx]
    try:
        if self.cache_training_data:
            audio = self.audio_files[idx] # .copy()
        else:
            audio = self.load_file(audio_filename)

        #Run augmentations on this sample (including random crop)
        if self.augs is not None:
            audio = self.augs(audio)

        audio = audio.clamp(-1, 1)

        #Encode the file to assist in prediction
        if self.encoding is not None:
            audio = self.encoding(audio)

        out = audio 
        #print("__getitem__: out.shape =",out.shape)
        return out

    except Exception as e:
      print(f'Error loading file {audio_filename}: {e}')
      return self[random.randrange(len(self))]