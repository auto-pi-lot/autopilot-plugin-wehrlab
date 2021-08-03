from copy import copy
import typing
import numpy as np

import autopilot
from autopilot.tasks.nafc import Nafc
from autopilot.networking import Net_Node
from autopilot.utils.common import find_key_recursive
from autopilot import prefs

class Nafc_Gap(Nafc):
    PARAMS = copy(Nafc.PARAMS)
    del PARAMS['punish_stim']
    PARAMS['noise_amplitude'] = {'tag':'Amplitude of continuous white noise',
                                 'type': 'float'}

    def __init__(self, noise_amplitude = 0.01, **kwargs):
        """
        A Mild variation of :class:`Nafc` that starts continuous white noise that plays
        continuously while the task is active.

        Args:
            noise_amplitude (float): Multiplier used to scale amplitude of continuous noise
            **kwargs: passed to :class:`Nafc`
        """

        # Can't really have a white noise punishment when there is continuous noise
        kwargs['punish_stim'] = False
        kwargs['stim_light'] = False
        super(Nafc_Gap, self).__init__(**kwargs)

        self.logger.debug('starting background sound')
        self.noise_amplitude = noise_amplitude
        self.noise_duration = 10*1000 # 10 seconds
        self.noise = autopilot.get('sound', 'Noise')(duration=self.noise_duration,
                                  amplitude=self.noise_amplitude)

        self.noise.play_continuous()
        self.logger.debug('background sound started')


    def end(self):
        """
        Stop the task, ending the continuous white noise.
        """
        self.noise.stop_continuous()
        super(Nafc_Gap, self).end()


class Nafc_Gap_Laser(Nafc_Gap):
    PARAMS = copy(Nafc_Gap.PARAMS)
    PARAMS['laser_probability'] = {'tag': 'Probability (of trials whose targets match laser_mode) of laser being turned on (0-1)',
                                   'type':'float'}
    PARAMS['laser_mode'] = {'tag':'Laser Mode, laser will be possible when target == ?',
        'type':'list',
        'values':{
            'L':0,
            'R':1,
            'Both':2
        }}
    PARAMS['laser_freq'] = {'tag': 'Laser Pulse Frequency (Hz), list-like [20, 30]',
                            'type': 'str'}
    PARAMS['laser_duty_cycle'] = {'tag': 'Laser Duty Cycle (0-1), list-like [0.1, 0.2]',
                                  'type': 'str'}
    PARAMS['laser_durations'] = {'tag': 'Laser durations (ms), list-like [10, 20]. if blank, use durations from stimuli',
                                 'type': 'str'}
    PARAMS['arena_led_mode'] = {'tag': 'Arena LED Mode: always ON vs. on for longest stim duration during requests',
                                'type': 'list',
                                'values':{'ON': 0, 'STIM': 1}}

    HARDWARE = copy(Nafc_Gap.HARDWARE)

    HARDWARE['LASERS'] = {
        'LR': gpio.Digital_Out
    }

    HARDWARE['LEDS']['TOP'] = gpio.Digital_Out

    TrialData = copy(Nafc_Gap.TrialData)
    TrialData.laser = tables.Int32Col()
    TrialData.laser_duration = tables.Float32Col()
    TrialData.laser_freq = tables.Float32Col()
    TrialData.laser_duty_cycle = tables.Float32Col()


    def __init__(self,
                 laser_probability: float,
                 laser_mode: str,
                 laser_freq: typing.Union[str, list],
                 laser_duty_cycle: typing.Union[str, list],
                 laser_durations: typing.Union[str, list],
                 arena_led_mode: str = 'ON',
                 **kwargs):
        """
        Gap detection task with ability to control lasers via TTL logic for optogenetics

        :attr:`.laser_freq`, :attr:`.laser_duty_cycle`, and :attr:`.laser_durations` can be passed
        either as an integer (actually typically a string because of the way the value is pulled from the protocol wizard),
        or as a list -- the product of values for all three are generated and presented equiprobably
        (eg. if ``laser_freq = 20, laser_duty_cycle=[0.1, 0.2, 0.3], laser_durations = [1, 2, 4, 8]`` were passed,
        then 1*3*4=12 different laser conditions would be possible.

        .. note::

            Subclasses like these will be made obsolete with the completion of stimulus managers

        Args:
            laser_probability (float): if trial satisfies ``laser_mode``, probability that laser will be
            laser_mode ('L', 'R', or 'Both'): Selects whether the laser is to be presented when :attr:`.target` is ``'L', 'R'`` or Either.
            laser_freq (str, list): Single value or list of possible laser frequencies in Hz
            laser_duty_cycle (str, list): Single value or list of possible duty cycles from 0-1
            laser_durations (str, list): Single value or list of possible laser durations (total time laser is on) in ms
            arena_led_mode ('ON', 'STIM'): Whether the overhead LED should always be 'ON', or whether it should be illuminated for the duration of the longest stimulus at every request

        Attributes:
            laser_conditions (tuple): tuple of dicts of laser conditions, of format:
                ::

                    {
                    'freq': laser frequency,
                    'duty_cycle': laser duty cycle,
                    'duration': laser duration,
                    'script_id': script ID for the series used by the laser Digital Out object,
                    }
        """
        self.laser_probability = float(laser_probability)
        self.laser_mode = laser_mode
        self.arena_led_mode = arena_led_mode

        # accept them if we're given a list of values, otherwise they should be strings that are single values,
        # which are put in lists so they can be iterated over in the product iterator.
        self.laser_freq = laser_freq if isinstance(laser_freq, list) else [float(laser_freq)] # type: list
        self.laser_duty_cycle = laser_duty_cycle if isinstance(laser_duty_cycle, list) else [float(laser_duty_cycle)] # type: list
        self.laser_durations = laser_durations if isinstance(laser_durations, list) else [float(laser_durations)] # type: list

        self.laser_conditions = tuple() # type: typing.Tuple[typing.Dict]

        super(Nafc_Gap_Laser, self).__init__(**kwargs)

        self.init_lasers()

        # -----------------------------------
        # create a pulse for the LED that's equal to the longest stimulus duration
        # use find_key_recursive to find all durations
        # FIXME: implement stimulus managers properly, including API to get attributes of stimuli
        if self.arena_led_mode == "ON":
            self.hardware['LEDS']['TOP'].turn(True)
        elif self.arena_led_mode == "STIM":
            stim_durations = list(find_key_recursive('duration', kwargs['stim']))
            max_duration = np.max(stim_durations)
            self.hardware['LEDS']['TOP'].store_series('on', values=1, durations=max_duration )
        else:
            raise ValueError(f'arena_led_mode must be one of ON or STIM, got {self.arena_led_mode}')

    def init_lasers(self):
        """
        Given :attr:`.laser_freq`, :attr:`.laser_duty_cycle`, :attr:`.laser_durations` ,
        create series with :meth:`.Digital_Out.store_series` and populate :attr:`.laser_conditions`
        """

        # TODO: This really should be something that Digital_Out should be capable of doing -- specifying series from these params...

        # --------------------------------------
        # create description of laser pulses
        # iterate over laser condition lists,
        # create lists of values (on/off) and durations (ms)
        # use them to create pigpio scripts using the Digital_Out.store_series() method
        # --------------------------------------------------
        self.logger.debug('Creating laser and LED series')
        # create iterator
        condition_iter = itertools.product(self.laser_durations, self.laser_freq, self.laser_duty_cycle)

        conditions = []
        for duration, freq, duty_cycle in condition_iter:
            # get the durations of on and off for a single cycle
            cycle_duration = (1/freq)*1000 # convert Hz to ms
            duty_cycle_on = duty_cycle * cycle_duration
            duty_cycle_off = cycle_duration - duty_cycle_on

            # get number of repeats to make
            n_cycles = int(np.floor(duration/cycle_duration))
            durations = [duty_cycle_on, duty_cycle_off]*n_cycles
            values = [1, 0]*n_cycles

            # pad any incomplete cycles
            dur_remaining = duration-(cycle_duration*n_cycles)
            if dur_remaining < duty_cycle_on:
                durations.append(dur_remaining)
                values.append(1)
            else:
                durations.extend([duty_cycle_on, dur_remaining-duty_cycle_on])
                values.extend([1, 0])

            # create ID from params
            script_id = f"{duration}_{freq}_{duty_cycle}"


            # store pulses as pigpio scripts
            self.hardware['LASERS']['LR'].store_series(script_id, values=values, durations=durations)

            conditions.append({
                'freq':freq,
                'duty_cycle': duty_cycle,
                'duration': duration,
                'script_id': script_id
            })

        self.laser_conditions = tuple(conditions)

        self.logger.debug(f'Laser series created with {len(self.laser_conditions)} conditions')




    def request(self,*args,**kwargs):
        """
        Call the superclass request method, and then compute laser presentation logic.

        If :attr:`.target` == :attr:`.laser_mode`, spin for a laser trial depending on :attr:`.laser_probability`.

        If we present a laser on this trial, we randomly draw from :attr:`.laser_conditions` and call the appropriate script.
        """
        # call the super method
        data = super(Nafc_Gap_Laser, self).request(*args, **kwargs)

        # handle laser logic
        # if the laser_mode is fulfilled, roll for a laser
        test_laser = False
        if self.laser_mode == "L" and self.target == "L":
            test_laser = True
        elif self.laser_mode == "R" and self.target == "R":
            test_laser = True
        elif self.laser_mode == "Both":
            test_laser = True

        duration = 0
        duty_cycle = 0
        frequency = 0
        do_laser = False
        if test_laser:
            # if we've rolled correctly for a laser...
            if np.random.rand() <= self.laser_probability:
                do_laser = True

                # If we're doing laser, we don't do the stim, so we pop the first two triggers
                del self.triggers['C'][:2]

                # pick a random duration
                condition = np.random.choice(self.laser_conditions)
                duration = condition['duration']
                duty_cycle = condition['duty_cycle']
                frequency = condition['freq']
                # insert the laser triggers before the rest of the triggers
                self.triggers['C'].insert(0, lambda: self.hardware['LASERS']['LR'].series(id=condition['script_id']))

        # always turn the light on
        if self.arena_led_mode == "STIM":
            self.triggers['C'].insert(0, lambda: self.hardware['LEDS']['TOP'].series(id='on'))


        # store the data about the laser status
        data['laser'] = do_laser
        data['laser_duration'] = duration
        data['laser_duty_cycle'] = duty_cycle
        data['laser_frequency'] = frequency

        # return the data created by the original task
        return data

    def set_leds(self, color_dict=None):
        """
        Set the color of all LEDs at once.

        Override base method to exclude TOP led

        Args:
            color_dict (dict): If None, turn LEDs off, otherwise like:

                {'pin': [R,G,B],
                'pin2: [R,G,B]}


        """
        # We are passed a dict of ['pin']:[R, G, B] to set multiple colors
        # All others are turned off
        if not color_dict:
            color_dict = {}
        for k, v in self.hardware['LEDS'].items():
            if k == "TOP":
                continue
            if k in color_dict.keys():
                v.set(color_dict[k])
            else:
                v.set(0)

