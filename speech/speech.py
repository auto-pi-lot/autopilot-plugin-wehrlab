from autopilot.stim.sound.sounds import File

class Speech(File):
    """
    Speech subclass of File sound.

    Example of custom sound class - PARAMS are changed, but nothing else.
    """

    type='Speech'
    PARAMS = ['path', 'amplitude', 'speaker', 'consonant', 'vowel', 'token']
    def __init__(self, path, speaker, consonant, vowel, token, amplitude=0.05, **kwargs):
        """
        Args:
            speaker (str): Which Speaker recorded this speech token?
            consonant (str): Which consonant is in this speech token?
            vowel (str): Which vowel is in this speech token?
            token (int): Which token is this for a given combination of speaker, consonant, and vowel
        """
        super(Speech, self).__init__(path, amplitude, **kwargs)

        self.speaker = speaker
        self.consonant = consonant
        self.vowel = vowel
        self.token = token

        # sound is init'd in the superclass
