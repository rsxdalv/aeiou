# AUTOGENERATED! DO NOT EDIT! File to edit: ../02_viz.ipynb.

# %% auto 0
__all__ = ['plotly_already_setup', 'embeddings_table', 'proj_pca', 'pca_point_cloud', 'on_colab', 'setup_plotly',
           'show_pca_point_cloud', 'print_stats', 'mel_spectrogram', 'spectrogram_image', 'audio_spectrogram_image',
           'generate_melspec', 'playable_spectrogram', 'tokens_spectrogram_image', 'plot_jukebox_embeddings']

# %% ../02_viz.ipynb 5
import math
import os
from pathlib import Path
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.cm as cm
import matplotlib.pyplot as plt 
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
import numpy as np
from PIL import Image

import torch
from torch import optim, nn
from torch.nn import functional as F
import torchaudio
import torchaudio.transforms as T
import librosa 
from einops import rearrange

import wandb
import numpy as np
import pandas as pd

from IPython.display import display, HTML  # just for displaying inside notebooks

from .core import load_audio

# for playable spectrograms:
import plotly.graph_objects as go
import holoviews as hv 
import panel as pn
from bokeh.resources import INLINE
from scipy.signal import spectrogram
#from bokeh.io import output_notebook

# %% ../02_viz.ipynb 6
def embeddings_table(tokens):
    "make a table of embeddings for use with wandb"
    features, labels = [], []
    embeddings = rearrange(tokens, 'b d n -> b n d') # each demo sample is n vectors in d-dim space
    for i in range(embeddings.size()[0]):  # nested for's are slow but sure ;-) 
        for j in range(embeddings.size()[1]):
            features.append(embeddings[i,j].detach().cpu().numpy())
            labels.append([f'demo{i}'])    # labels does the grouping / color for each point
    features = np.array(features)
    #print("\nfeatures.shape = ",features.shape)
    labels = np.concatenate(labels, axis=0)
    cols = [f"dim_{i}" for i in range(features.shape[1])]
    df   = pd.DataFrame(features, columns=cols)
    df['LABEL'] = labels
    return wandb.Table(columns=df.columns.to_list(), data=df.values)

# %% ../02_viz.ipynb 7
def proj_pca(tokens, proj_dims=3):
    "this projects via PCA, grabbing the first _3_ dimensions"
    A = rearrange(tokens, 'b d n -> (b n) d') # put all the vectors into the same d-dim space
    if A.shape[-1] > proj_dims: 
        (U, S, V) = torch.pca_lowrank(A)
        proj_data = torch.matmul(A, V[:, :proj_dims])  # this is the actual PCA projection step
    else:
        proj_data = A
    return torch.reshape(proj_data, (tokens.size()[0], -1, proj_dims)) # put it in shape [batch, n, 3]

# %% ../02_viz.ipynb 9
def pca_point_cloud(
    tokens,                  # embeddings / latent vectors. shape = (b, d, n)
    color_scheme='batch',    # 'batch': group by sample, otherwise color sequentially
    output_type='wandbobj',  # plotly | points | wandbobj.  NOTE: WandB can do 'plotly' directly!
    mode='markers',    # plotly scatter mode.  'lines+markers' or 'markers'
    size=3,            # size of the dots
    line=dict(color='rgba(10,10,10,0.01)'),  # if mode='lines+markers', plotly line specifier. cf. https://plotly.github.io/plotly.py-docs/generated/plotly.graph_objects.scatter3d.html#plotly.graph_objects.scatter3d.Line
    ):
    "returns a 3D point cloud of the tokens using PCA"
    data = proj_pca(tokens).cpu().numpy()
    points = [] 
    if color_scheme=='batch':
        cmap, norm = cm.tab20, Normalize(vmin=0, vmax=data.shape[0])
    else: 
        cmap, norm = cm.viridis, Normalize(vmin=0, vmax=data.shape[1])
    for bi in range(data.shape[0]):  # batch index
        if color_scheme=='batch': [r, g, b, _] = [int(255*x) for x in cmap(norm(bi))] 
        for n in range(data.shape[1]):
            if color_scheme!='batch': [r, g, b, _] = [int(255*x) for x in cmap(norm(n))] 
            points.append([data[bi,n,0], data[bi,n,1], data[bi,n,2], r, g, b])

    point_cloud = np.array(points)
        
    if output_type == 'points':
        return point_cloud
    elif output_type =='plotly':
        fig = go.Figure(data=[go.Scatter3d(
            x=point_cloud[:,0], y=point_cloud[:,1], z=point_cloud[:,2], 
            marker=dict(size=size, opacity=0.6, color=point_cloud[:,3:6]),
            mode=mode, 
            # show batch index and time index in tooltips: 
            text=[ f'bi: {i}, ti: {j}' for i in range(data.shape[0]) for j in range(data.shape[1]) ],
            line=line,
            )])
        fig.update_layout(margin=dict(l=0, r=0, b=0, t=0)) # tight layout
        return fig
    else:
        return wandb.Object3D(point_cloud)

# %% ../02_viz.ipynb 11
# have to do a little extra stuff to make this come out in the docs.  This part taken from drscotthawley's `mrspuff` library
def on_colab():   # cf https://stackoverflow.com/questions/53581278/test-if-notebook-is-running-on-google-colab
    """Returns true if code is being executed on Colab, false otherwise"""
    try:
        return 'google.colab' in str(get_ipython())
    except NameError:    # no get_ipython, so definitely not on Colab
        return False 
    
plotly_already_setup = False
def setup_plotly(nbdev=True):
    """Plotly is already 'setup' on colab, but on regular Jupyter notebooks we need to do a couple things"""
    global plotly_already_setup 
    if plotly_already_setup: return 
    if nbdev and not on_colab():  # Nick Burrus' code for normal-Juptyer use with plotly & nbdev
        import plotly.io as pio
        pio.renderers.default = 'notebook_connected'
        js = '<script src="https://cdnjs.cloudflare.com/ajax/libs/require.js/2.3.6/require.min.js" integrity="sha512-c3Nl8+7g4LMSTdrm621y7kf9v3SDPnhxLNhcjFJbKECVnmZHTdo+IRO05sNLTH/D3vA6u1X32ehoLC7WFVdheg==" crossorigin="anonymous"></script>'
        display(HTML(js))
    plotly_already_setup = True 
    
def show_pca_point_cloud(tokens, color_scheme='batch', mode='markers', line=dict(color='rgba(10,10,10,0.01)')):
    "display a 3d scatter plot of tokens in notebook"
    setup_plotly()
    fig = pca_point_cloud(tokens, color_scheme=color_scheme, output_type='plotly', mode=mode, line=line)
    fig.show()

# %% ../02_viz.ipynb 17
def print_stats(waveform, sample_rate=None, src=None, print=print):
    "print stats about waveform. Taken verbatim from pytorch docs."
    if src:
        print(f"-" * 10)
        print(f"Source: {src}")
        print(f"-" * 10)
    if sample_rate:
        print(f"Sample Rate: {sample_rate}")
    print(f"Shape: {tuple(waveform.shape)}")
    print(f"Dtype: {waveform.dtype}")
    print(f" - Max:     {waveform.max().item():6.3f}")
    print(f" - Min:     {waveform.min().item():6.3f}")
    print(f" - Mean:    {waveform.mean().item():6.3f}")
    print(f" - Std Dev: {waveform.std().item():6.3f}")
    print('')
    print(f"{waveform}")
    print('')

# %% ../02_viz.ipynb 21
def mel_spectrogram(waveform, power=2.0, sample_rate=48000, db=False, n_fft=1024, n_mels=128, debug=False):
    "calculates data array for mel spectrogram (in however many channels)"
    win_length = None
    hop_length = n_fft//2 # 512

    mel_spectrogram_op = T.MelSpectrogram(
        sample_rate=sample_rate, n_fft=n_fft, win_length=win_length, 
        hop_length=hop_length, center=True, pad_mode="reflect", power=power, 
        norm='slaney', onesided=True, n_mels=n_mels, mel_scale="htk")

    melspec = mel_spectrogram_op(waveform.float())
    if db: 
        amp_to_db_op = T.AmplitudeToDB()
        melspec = amp_to_db_op(melspec)
    if debug:
        print_stats(melspec, print=print) 
        print(f"torch.max(melspec) = {torch.max(melspec)}")
        print(f"melspec.shape = {melspec.shape}")
    return melspec

# %% ../02_viz.ipynb 22
def spectrogram_image(
        spec, 
        title=None, 
        ylabel='freq_bin', 
        aspect='auto', 
        xmax=None, 
        db_range=[35,120], 
        justimage=False,
        figsize=(5, 4), # size of plot (if justimage==False)
    ):
    "Modified from PyTorch tutorial https://pytorch.org/tutorials/beginner/audio_feature_extractions_tutorial.html"
    fig = Figure(figsize=figsize, dpi=100) if not justimage else Figure(figsize=(4.145, 4.145), dpi=100, tight_layout=True)
    canvas = FigureCanvasAgg(fig)
    axs = fig.add_subplot()
    spec = spec.squeeze()
    im = axs.imshow(librosa.power_to_db(spec), origin='lower', aspect=aspect, vmin=db_range[0], vmax=db_range[1])
    if xmax:
        axs.set_xlim((0, xmax))
    if justimage:
        axs.axis('off')
        plt.tight_layout()
    else: 
        axs.set_ylabel(ylabel)
        axs.set_xlabel('frame')
        axs.set_title(title or 'Spectrogram (dB)')
        fig.colorbar(im, ax=axs)
    canvas.draw()
    rgba = np.asarray(canvas.buffer_rgba())
    im = Image.fromarray(rgba)
    if justimage: # remove tiny white border
        b = 15 # border size 
        im = im.crop((b,b, im.size[0]-b, im.size[1]-b))
        #print(f"im.size = {im.size}")
    return im

# %% ../02_viz.ipynb 23
def audio_spectrogram_image(waveform, power=2.0, sample_rate=48000, print=print, db=False, db_range=[35,120], justimage=False, log=False):
    "Wrapper for calling above two routines at once, does Mel scale; Modified from PyTorch tutorial https://pytorch.org/tutorials/beginner/audio_feature_extractions_tutorial.html"
    melspec = mel_spectrogram(waveform, power=power, db=db, sample_rate=sample_rate, debug=log)
    melspec = melspec[0] # TODO: only left channel for now
    return spectrogram_image(melspec, title="MelSpectrogram", ylabel='mel bins (log freq)', db_range=db_range, justimage=justimage)

# %% ../02_viz.ipynb 27
# Original code by Scott Condron (@scottire) of Weights and Biases, edited by @drscotthawley
# cf. @scottire's original code here: https://gist.github.com/scottire/a8e5b74efca37945c0f1b0670761d568
# and Morgan McGuire's edit here; https://github.com/morganmcg1/wandb_spectrogram


# helper routine; a bit redundant given what else is in this repo
def generate_melspec(audio_data, sample_rate=48000, power=2.0, n_fft = 1024, win_length = None, hop_length = None, n_mels = 128):
    "helper routine for playable_spectrogram"
    if hop_length is None:
         hop_length = n_fft//2

    # convert to torch
    audio_data = torch.tensor(audio_data, dtype=torch.float32)

    mel_spectrogram_op = T.MelSpectrogram(
        sample_rate=sample_rate,
        n_fft=n_fft,
        win_length=win_length,
        hop_length=hop_length,
        center=True,
        pad_mode="reflect",
        power=power,
        norm="slaney",
        onesided=True,
        n_mels=n_mels,
        mel_scale="htk",
    )

    melspec = mel_spectrogram_op(audio_data).numpy()
    mel_db = np.flipud(librosa.power_to_db(melspec))
    return mel_db


# the main routine
def playable_spectrogram(
    waveform,                # audio, PyTorch tensor 
    sample_rate=48000,       # sample rate in Hz
    specs:str='all', # see docstring below
    layout:str='row',        # 'row' or 'grid'
    height=170,              # height of spectrogram image
    width=400,               # width of spectrogram image
    cmap='viridis',           # colormap string for Holoviews, see https://holoviews.org/user_guide/Colormaps.html
    output_type='wandb',          # 'wandb', 'html_file', 'live': use live for notebooks
    debug=True               # flag for internal print statements
    ):
    '''
    Takes a tensor input and returns a [wandb.]HTML object with spectrograms of the audio
    specs : 
      "all_specs", spetrograms only
      "all", all plots
      "melspec", melspectrogram only
      "spec", spectrogram only
      "wave_mel", waveform and melspectrogram only
      "waveform", waveform only, equivalent to wandb.Audio object
      
      Limitations: spectrograms show channel 0 only (i.e., mono)
    '''
    hv.extension("bokeh", logo=False)
    
    audio_data = waveform.cpu().numpy()

    duration =  audio_data.shape[-1]/sample_rate 
    if len(audio_data.shape) > 1:
        mono_audio = audio_data[0,:] # MONO ONLY get one channel, for spectrograms

    # for the audio widget, it works best if you save-a-file-read-a-file
    # need to convert to int for Panel Audio element
    #audio_ints =  np.clip( audio_data*32768 , -32768, 32768).astype('int16')
    # Audio widget
    #audio = pn.pane.Audio(audio_ints, sample_rate=sample_rate, name='Audio', throttle=10)
    tmp_audio_file = f'audio_out.wav' # holoview expects file to persist _{int(np.random.rand()*10000)}.wav' # rand number is just to allow parallel operation
    torchaudio.save(tmp_audio_file, waveform.cpu() ,sample_rate)
    audio = pn.pane.Audio(tmp_audio_file,  name='Audio', throttle=10)
    #os.remove(tmp_audio_file)  # but we don't want a ton of files to accumulate on the disk 

    # Add HTML components
    line = hv.VLine(0).opts(color='red')
    line2 = hv.VLine(0).opts(color='green')
    line3 = hv.VLine(0).opts(color='white')

    slider = pn.widgets.FloatSlider(end=duration, visible=False, step=0.001)
    slider.jslink(audio, value='time', bidirectional=True)
    slider.jslink(line, value='glyph.location')
    slider.jslink(line2, value='glyph.location')
    slider.jslink(line3, value='glyph.location')

    # Spectogram plot
    if specs in ['spec','all_specs,','all']:
        f, t, sxx = spectrogram(mono_audio, sample_rate)
        spec_gram_hv = hv.Image((t, f, np.log10(sxx)), ["Time (s)", "Frequency (Hz)"]).opts(
            width=width, height=height, labelled=[], axiswise=True, color_levels=512, cmap=cmap)
        spec_gram_hv = spec_gram_hv.options(xlabel="Time (s)", ylabel="Frequency (Hz)") # for some reason it was ignoring my axis labels the in the Image definition

        spec_gram_hv *= line
    else: 
        spec_gram_hv = None

    # Melspectogram plot
    if specs in ['melspec','all_specs','all','wave_mel']:
        mel_db = generate_melspec(mono_audio, sample_rate=sample_rate, power=2.0, n_fft = 1024, n_mels = 100)
        melspec_gram_hv = hv.Image(mel_db, ["Time (s)", "Mel Freq"], bounds=(0, 0, duration, mel_db.max()), ).opts(
            width=width, height=height, labelled=[], axiswise=True, color_levels=512, cmap=cmap) 
        melspec_gram_hv = melspec_gram_hv.options(xlabel="Time (s)", ylabel="Mel Freq")
        melspec_gram_hv *= line3
    else:
        melspec_gram_hv = None

    # Waveform plot (multichannel as colors atop one another)
    if specs in ['waveform','all','wave_mel']:
        time = np.linspace(0, len(mono_audio)/sample_rate, num=len(mono_audio))
        overlay_curves = []
        for i in range(audio_data.shape[0]):
            overlay_curves.append(hv.Curve((time, audio_data[i]), "Time (s)", "amplitude").opts(
                width=width, height=height, axiswise=True))
        line_plot_hv = hv.Overlay(overlay_curves).opts(width=width, height=height)
        #line_plot_hv = hv.Curve((time, mono_audio), "Time (s)", "amplitude").opts(
        #    width=width, height=height, axiswise=True)
        line_plot_hv *= line2
    else:
        line_plot_hv = None


    # Create HTML layout
    html_file_name = "audio_spec.html"

    if layout == 'grid': 
        combined = pn.GridBox(audio, spec_gram_hv, line_plot_hv, melspec_gram_hv, slider, ncols=2, nrows=2)
    else: #  'row'
        combined = pn.Row(audio, line_plot_hv,  melspec_gram_hv, spec_gram_hv, slider)
        

    if output_type == 'live':
        return combined
    
    combined = combined.save(html_file_name)
    return wandb.Html(html_file_name) if output_type=='wandb' else html_file_name

# %% ../02_viz.ipynb 31
from matplotlib.ticker import AutoLocator 
def tokens_spectrogram_image(
        tokens,                # the embeddings themselves (in some diffusion codes these are called 'tokens')
        aspect='auto',         # aspect ratio of plot
        title='Embeddings',    # title to put on top
        ylabel='index',        # label for y axis of plot
        cmap='coolwarm',       # colormap to use. (default used to be 'viridis')
        symmetric=True,        # make color scale symmetric about zero, i.e. +/- same extremes
        figsize=(8, 4),       # matplotlib size of the figure
        dpi=100,               # dpi of figure
        mark_batches=False,     # separate batches with dividing lines
        debug=False,           # print debugging info
    ):
    "for visualizing embeddings in a spectrogram-like way"
    batch_size, dim, samples = tokens.shape
    embeddings = rearrange(tokens, 'b d n -> (b n) d')  # expand batches in time
    vmin, vmax = None, None
    if symmetric:
        vmax = torch.abs(embeddings).max()
        vmin = -vmax
        
    fig = Figure(figsize=figsize, dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    if symmetric: 
        subtitle = f'min={embeddings.min():0.4g}, max={embeddings.max():0.4g}'
        ax.set_title(title+'\n')
        ax.text(x=0.435, y=0.9, s=subtitle, fontsize=11, ha="center", transform=fig.transFigure)
    else:
        ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel('time frame (samples, in batches)')
    if mark_batches:
        intervals = np.arange(batch_size)*samples
        if debug: print("intervals = ",intervals)
        ax.vlines(intervals, -10, dim+10, color='black', linestyle='dashed', linewidth=1)

    im = ax.imshow(embeddings.cpu().numpy().T, origin='lower', aspect=aspect, interpolation='none', cmap=cmap, vmin=vmin,vmax=vmax) #.T because numpy is x/y 'backwards'
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    canvas.draw()
    rgba = np.asarray(canvas.buffer_rgba())
    return Image.fromarray(rgba)

# %% ../02_viz.ipynb 35
def plot_jukebox_embeddings(zs, aspect='auto'):
    "makes a plot of jukebox embeddings"
    fig, ax = plt.subplots(nrows=len(zs))
    for i, z in enumerate(zs):
        #z = torch.squeeze(z)
        z = z.cpu().numpy()
        x = np.arange(z.shape[-1])
        im = ax[i].imshow(z, origin='lower', aspect=aspect, interpolation='none')

    #plt.legend()
    plt.ylabel("emb (top=fine, bottom=coarse)")
    return {"chart": plt}
