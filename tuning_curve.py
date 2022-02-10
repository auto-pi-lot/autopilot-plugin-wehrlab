import datetime
import itertools
import tables
import threading
from copy import copy
import typing
import time

import numpy as np

import autopilot.hardware.gpio
from autopilot.hardware import gpio
from autopilot.tasks import Task
from collections import OrderedDict as odict
from autopilot.networking.node import Net_Node
from autopilot.stim.sound import sounds
from autopilot.stim import init_manager


from autopilot import prefs
import pdb
import pickle

TASK = 'TuningCurve'

class TuningCurve(Task):

	# play an array of tones and/or whitenoise

	STAGE_NAMES = ["playtone"] 
	#there's only one stage, which consists of a single LED flash and play a tone


	PARAMS = odict()
	PARAMS['inter_stimulus_interval'] = {'tag':'Inter Stimulus Interval (ms)', 'type':'int'}
	PARAMS['frequencies'] = {'tag':'list of tone frequencies in Hz','type':'str'}
	PARAMS['amplitudes'] = {'tag':'list of tone amplitudes, 0-1','type':'str'}
	PARAMS['duration'] = {'tag':'tone duration in ms','type':'str'}

	class TrialData(tables.IsDescription):
	        """This class allows the Subject object to make a data table with the
			correct data types. You must update it for any new data you'd like to store
			For a blinking LED there isn't much in the way of data, but we (probably) need
			to return at least something  """
	        trial_num = tables.Int32Col()

	"""the only hardware here is a digital out to flash the LED.  """
	HARDWARE = {
		'LEDS':{ 
	       'dLED': gpio.Digital_Out 
        }
	}


	def __init__(self, frequencies, amplitudes, duration, stage_block=None,  inter_stimulus_interval=500, **kwargs):
		super(TuningCurve, self).__init__()
		# explicitly type everything to be safe.
		self.inter_stimulus_interval = int(inter_stimulus_interval)
		self.frequencies = [float(i) for i in frequencies]
		self.amplitudes = [float(i) for i in amplitudes]
		duration = int(duration)
		Tone=autopilot.get('sound', 'Tone')
		self.sounds=[Tone(freq, duration, amp) for freq, amp in product(self.amplitudes, self.frequencies)]
		
		# This allows us to cycle through the task by just repeatedly calling self.stages.next()
		stage_list = [self.playtone] #a list of only one stage, the pulse
		self.num_stages = len(stage_list)
		self.stages = itertools.cycle(stage_list)
		self.trial_counter = itertools.count()

		# Initialize hardware
		self.init_hardware()
		self.logger.debug('Hardware initialized')

		self.stage_block = stage_block
		#this is the threading.event object that is used to advance from one stage to the next 

		# Initialize stim manager
		#if not stim:
		#	raise RuntimeError("Cant instantiate task without stimuli!")
		#else:
		#	self.stim_manager = init_manager(stim)
		#self.logger.debug('Stimulus manager initialized')
		self.logger.debug('no Stimulus manager this time')

		#self.stim_manager = init_sounds(stim)
		#self.logger.debug('Stimulus manager initialized')
		

	##################################################################################
	# Stage Functions
	##################################################################################
	def playtone(self,*args,**kwargs):
		"""
		Stage 0: a single tone and interval.
		Returns: just the trial number
		"""


		self.hardware['LEDS']['dLED'].set(1)

		
		
		# choose a random sound
		asound = random.choice(self.sounds)
		asound.buffer()
		asound.play()
		
		#sound_info = {k:getattr(asound, k) for k in self.stim.PARAMS}
		sound_info = {frequency:getattr(asound, frequency)}
		
		self.logger.debug(f'playtone: {sound_info} ')

		inter_stimulus_interval=self.inter_stimulus_interval

		self.hardware['LEDS']['dLED'].set(0)
		#self.logger.debug('light off')
		time.sleep(inter_stimulus_interval/1000)

		self.current_trial = next(self.trial_counter)
		self.current_stage = 0
		self.logger.debug(f'trial {self.current_trial}')

		self.stage_block.set()
		#this clears the stage block so we advance to the next stage 

		
		#data.update(sound_info)
		#data.update({'type':self.stim.type})


		#return the trial number as data
		data = {'trial_num' : self.current_trial}
		return data







