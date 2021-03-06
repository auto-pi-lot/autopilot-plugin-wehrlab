import datetime
import itertools
import tables
import threading
import typing
import ast
import random
import time

import autopilot
import autopilot.hardware.gpio
from autopilot.hardware import gpio
from autopilot.tasks import Task
from collections import OrderedDict as odict

TASK = 'TuningCurve'

class TuningCurve(Task):
    # play an array of tones 
    # signal the start of the protocol with a pulse on ProtocolStart channel
    # signal the onset of each tone with a pulse on SoundTrigger channel


    STAGE_NAMES = ["playtone"]
    # there's only one stage, which consists of a single LED flash and play a tone

    PARAMS = odict()
    PARAMS['inter_stimulus_interval'] = {'tag': 'Inter Stimulus Interval (ms)', 'type': 'int'}
    PARAMS['frequencies'] = {'tag':'Frequencies (Hz), like [1000, 2000]', 'type':'str'}
    PARAMS['amplitudes'] = {'tag': 'Amplitudes (0-1) like [0.1, 0.2]', 'type':'str'}
    PARAMS['duration'] = {'tag':'Duration (ms) of each tone', 'type':'int'}
    PARAMS['ramp'] = {'tag':'Ramp (ms) for rising/falling edge of each tone', 'type':'int'}


    class TrialData(tables.IsDescription):
        """This class allows the Subject object to make a data table with the
        correct data types. You must update it for any new data you'd like to store
        For a blinking LED there isn't much in the way of data, but we (probably) need
        to return at least something  """
        trial_num = tables.Int32Col()
        timestamp = tables.StringCol(26)
        frequency = tables.Float32Col()
        amplitude = tables.Float32Col()
        ramp = tables.Float32Col()


    """the only hardware here is a digital out to flash the LED.  """
    HARDWARE = {
        'GPIO': {
            'ProtocolStart': gpio.Digital_Out,
            'SoundTrigger': gpio.Digital_Out
        }
    }

    def __init__(self,
                 frequencies: typing.List[float],
                 amplitudes: typing.List[float],
                 duration:int = 500,
                 ramp:float = 3,
                 stage_block=None,
                 inter_stimulus_interval=500,
                 **kwargs):

        super(TuningCurve, self).__init__()

        ## Unpack args
        # explicitly type everything to be safe.
        self.inter_stimulus_interval = int(inter_stimulus_interval)
        if isinstance(frequencies, str):
            frequencies = ast.literal_eval(frequencies)
        if isinstance(amplitudes, str):
            amplitudes = ast.literal_eval(amplitudes)

        self.frequencies = [float(f) for f in frequencies]
        self.amplitudes = [float(a) for a in amplitudes]
        self.duration = int(duration)
        self.ramp = float(ramp)

        # This allows us to cycle through the task by just repeatedly calling self.stages.next()
        stage_list = [self.playtone]  # a list of only one stage, the pulse
        self.num_stages = len(stage_list)
        self.stages = itertools.cycle(stage_list)
        self.trial_counter = itertools.count()

        # Initialize hardware
        self.init_hardware()
        self.logger.debug('Hardware initialized')

        # make sounds from frequencies and amplitudes
        Tone = autopilot.get('sound', 'Tone')
        self.sounds = [Tone(frequency=freq, amplitude=amp, duration=duration, ramp=ramp) for freq, amp in itertools.product(self.frequencies, self.amplitudes)]
        self.logger.debug(f'{len(self.sounds)} Tones initialized')

        # make a series to pulse our ProtocolStart and SoundTrigger timing signals
        self.hardware['GPIO']['ProtocolStart'].store_series(id='pulse', values=[1], durations=[1], unit='ms')
        self.hardware['GPIO']['SoundTrigger'].store_series(id='pulse', values=[1], durations=[1], unit='ms')

        # this is the threading.event object that is used to advance from one stage to the next
        if stage_block is None:
            stage_block = threading.Event()
        self.stage_block = stage_block

        # Timer object to handle ISI delays
        self.isi_timer = None # type: typing.Optional[threading.Timer]

        self.logger.debug('Task initialized')
        #send timing signal for start of protocol
        self.hardware['GPIO']['ProtocolStart'].series(id='pulse')

        #wait for an ISI before delivering first tone 
        time.sleep(self.inter_stimulus_interval/1000) 


    ##################################################################################
    # Stage Functions
    ##################################################################################
    def playtone(self, *args, **kwargs):
        """
        Stage 0: a single tone and interval.
        Returns: just the trial number
        """
        # clear stage block to not continuously cycle
        self.stage_block.clear()

        # choose a sound
        sound = random.choice(self.sounds)
        sound.buffer()

        timestamp = datetime.datetime.now().isoformat()
        # timing signal for SoundTrigger 
        self.hardware['GPIO']['SoundTrigger'].series(id='pulse')
        sound.play()
        self.logger.debug(f"played sound with frequency {sound.frequency} and amplitude {sound.amplitude} and ramp {sound.ramp}")


        # get data to return
        self.current_trial = next(self.trial_counter)
        self.current_stage = 0
        data = {
            'trial_num': self.current_trial,
            'timestamp': timestamp,
            'frequency': sound.frequency,
            'amplitude': sound.amplitude,
            'ramp': sound.ramp
        }

        # set a timer to clear the stage block after the ISI
        self.isi_timer = threading.Timer(self.inter_stimulus_interval/1000, self.stage_block.set)
        self.isi_timer.start()

        return data
