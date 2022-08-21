# AUTOGENERATED! DO NOT EDIT! File to edit: ../01_datasets.ipynb.

# %% auto 0
__all__ = ['PadCrop', 'PhaseFlipper', 'FillTheNoise', 'RandPool', 'NormInputs', 'Mono', 'Stereo', 'RandomGain', 'AudioDataset']

# %% ../01_datasets.ipynb 5
import torch
import torch.nn as nn
import torchaudio
from torchaudio import transforms as T
from torchvision import transforms as VT
import random
import os
import tqdm
from multiprocessing import Pool, cpu_count
from functools import partial
from .core import load_audio, get_audio_filenames, is_silence
from fastcore.utils import store_attr 

# %% ../01_datasets.ipynb 7
class PadCrop(nn.Module):
    def __init__(self, 
        n_samples,           # length of chunk to extract from longer signal
        randomize=True,      # draw cropped chunk from a random position in audio file
        redraw_silence=True, # a chunk containing silence will be replaced with a new one
        silence_thresh=-60,  # threshold in dB below which we declare to be silence
        max_redraws=2        # when redrawing silences, don't do it more than this many
        ):
        super().__init__()
        store_attr()     # sets self.___ vars automatically
    
    def draw_chunk(self, signal):
        "here's the part that actually draws a cropped/padded chunk of audio from signal"
        n, s = signal.shape
        start = 0 if (not self.randomize) else torch.randint(0, max(0, s - self.n_samples) + 1, []).item()
        end = start + self.n_samples
        chunk = signal.new_zeros([n, self.n_samples])
        chunk[:, :min(s, self.n_samples)] = signal[:, start:end]
        return chunk
    
    def __call__(self, signal):
        "when part of the pipline, this will grab a padded/cropped chunk from signal"
        chunk = draw_chunk(signal)
        num_redraws = 0
        if redraw_silence and is_silence(chunk, thresh=self.silence_thresh) and (num_redraws < self.max_redraws):
            print(f"    PadCrop: Got silence.  Redrawing. Try {num_redraws+1} of {self.max_redraws}")
            chunk, num_redraws = draw_chunk(signal), num_redraws+1
        return chunk

# %% ../01_datasets.ipynb 8
class PhaseFlipper(nn.Module):
    "she was PHAAAAAAA-AAAASE FLIPPER, a random invert yeah"
    def __init__(self, 
        p=0.5  # probability that phase flip will be applied
        ):
        super().__init__()
        self.p = p
    def __call__(self, signal):
        return -signal if (random.random() < self.p) else signal

# %% ../01_datasets.ipynb 9
class FillTheNoise(nn.Module):
    "randomly adds a bit of noise, just to spice things up"
    def __init__(self, 
        p=0.33       # probability that noise will be added
        ):
        super().__init__()
        self.p = p
    def __call__(self, signal):
        return signal + 0.25*random.random()*(2*torch.rand_like(signal)-1) if (random.random() < self.p) else signal

# %% ../01_datasets.ipynb 10
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

# %% ../01_datasets.ipynb 11
class NormInputs(nn.Module):
    "Normalize inputs to [-1,1]. Useful for quiet inputs"
    def __init__(self, 
        do_norm=True    # controllable parameter for turning normalization on/off
        ):
        super().__init__()
        self.do_norm = do_norm
        self.eps = 1e-2
    def __call__(self, signal):
        return signal if (not self.do_norm) else signal/(torch.amax(signal,-1)[0] + self.eps)

# %% ../01_datasets.ipynb 12
class Mono(nn.Module):
    "convert audio to mono"
    def __call__(self, signal):
        return torch.mean(signal, dim=0) if len(signal.shape) > 1 else signal

# %% ../01_datasets.ipynb 13
class Stereo(nn.Module):
    "convert audio to stereo"
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

# %% ../01_datasets.ipynb 14
class RandomGain(nn.Module):
    "apply a random gain to audio"
    def __init__(self, min_gain, max_gain):
        super().__init__()
        self.min_gain = min_gain
        self.max_gain = max_gain

    def __call__(self, signal):
        gain = random.uniform(self.min_gain, self.max_gain)
        signal = signal * gain
        return signal

# %% ../01_datasets.ipynb 16
class AudioDataset(torch.utils.data.Dataset):
    """
    Reads from a tree of directories and serves up cropped bits from any and all audio files
    found therein. For efficiency, best if you "chunk" these files via chunkadelic
    modified from https://github.com/drscotthawley/audio-diffusion/blob/main/dataset/dataset.py
    """
    def __init__(self, 
        paths,             # list of strings of directory (/tree) names to draw audio files from
        sample_rate=48000, # audio sample rate in Hz
        sample_size=65536, # how many audio samples in each "chunk"
        random_crop=True,  # take chunks from random positions within files
        load_frac=1.0,     # fraction of total dataset to load
        cache_training_data=False,  # True = pre-load whole dataset into memory (not fully supported)
        num_gpus=8,        # used only when `cache_training_data=True`, to avoid duplicates,
        redraw_silence=True, # a chunk containing silence will be replaced with a new one
        silence_thresh=-60,  # threshold in dB below which we declare to be silence
        max_redraws=2,        # when redrawing silences, don't do it more than this many
        augs='PhaseFlipper()' # list of augmentation transforms **after PadCrop**, as a string
        ):
        super().__init__()
        store_attr()     # sets self.___ vars automatically
    
        self.filenames = []
    
        # Note moved augs definition to config file / cmd-line arg. 
        """self.augs = torch.nn.Sequential(
          PadCrop(sample_size, randomize=random_crop, ),
          #RandomGain(0.7, 1.0),
          #RandPool(),
          #FillTheNoise(),
          PhaseFlipper(),
          #NormInputs(do_norm=global_args.norm_inputs),
        )"""
        # base_augs are always applied
        base_augs = 'PadCrop(sample_size, randomize=random_crop, redraw_silence=redraw_silence, silence_thresh=silence_thresh, max_redraws=max_redraws)'

        #print(f"type(augs) = {type(augs)}")
        self.augs = torch.nn.Sequential( eval(f'{base_augs}, {augs}'), redraw_silence=redraw_silence )

        self.encoding = torch.nn.Sequential(  # TODO: technically this can be treated as part of an augmentation
          #Stereo() # if images can be 3-channel RGB, we can do stereo. 
          Mono()   # but RAVE expects mono, ....for now ;-) 
        )

        self.filenames = get_audio_filenames(paths)
        print(f"{len(self.filenames)} files found.")

        self.sr = sample_rate
        self.n_files = int(len(self.filenames)*self.load_frac)
        self.filenames = self.filenames[0:self.n_files]
        if self.cache_training_data: self.preload_files()

        self.convert_tensor = VT.ToTensor()

    def load_file_ind(self, file_list,i): # used when caching training data
        return load_audio(file_list[i]).cpu()

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
    
    
    def get_next_chunk(self, 
        idx     # the index of the file within the list of files
        ):
        "The heard of this whole dataset routine"
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
      
        except Exception as e:
          print(f'Error loading file {audio_filename}: {e}')
          return None
        
        if self.encoding is not None:  # Encode the file to assist in prediction
            audio = self.encoding(audio)
        
        
    def __getitem__(self, 
        idx     # the index of the file within the list of files
        ):
        audio = get_next_chunk(idx)
                
        # even with PadCrop set to reject silences, it could be that the whole file is silence; 
        num_redraws = 0 
        if (audio is None) or (redraw_silence and is_silence(audio, thresh=self.silence_thresh) and (num_redraws < self.max_redraws)):
            print(f"    AudioDataset.__getitem__: Got silence.  Redrawing. Try {num_redraws+1} of {self.max_redraws}")
            next_idx = random.randint(len(self.filenames))     # pick some other file at random
            audio, num_redraws = get_next_chunk(next_idx), num_redraws+1
               
        return self[random.randrange(len(self))] if (audio is None) else audio
