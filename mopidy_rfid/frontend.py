# encoding: utf-8
from __future__ import absolute_import, unicode_literals

import logging
import time
import pykka

from mopidy.core import PlaybackController
from mopidy.core import CoreListener
from mopidy.models import Track
from mopidy.core import PlaybackState

logger = logging.getLogger(__name__)

from mopidy_rfid import MFRC522 # https://github.com/brackendawson/MFRC522-python
from blink1py import open_blink1 # pip install blink1py, https://github.com/TronPaul/blink1py

class RFIDFailUID(Exception):
    pass

class RFIDReader(object):
    def __init__(self, frontend):
        self.mfr = MFRC522.MFRC522()
        logger.debug('Setting up card reader %r', self.mfr)
        self.cards = {}
        self.quitting = False
        self.last_card = None
        self.frontend = frontend
        self.b1 = open_blink1()

    def atexit(self):
        'Called on exit'
        logger.debug('Cleaning up for exit')
        self.mfr.MFRC522_StopCrypto1()

    def addCard(self, hexuid, cmd):
        'Add a cmd that is to be passed to subprocess.Popen when a card uid is recognised'
        if not self.cards.has_key(hexuid):
            self.cards[hexuid] = []
        self.cards[hexuid].append(cmd)

    def run(self):
        logger.debug('CardReader.run()')
        while self.quitting == False:
            status = None
            while status != self.mfr.MI_OK:
                (status,TagType) = self.mfr.MFRC522_Request(self.mfr.PICC_REQIDL)
            logger.debug('Got MFRC522_Request (status, TagType) = (%r, %r)', status, TagType)
            (status,uid) = self.mfr.MFRC522_Anticoll()
            logger.debug('Got MFRC522_Anticoll (status, uid) = (%r, %r)', status, uid)
            if status != self.mfr.MI_OK:
                #raise RFIDFailUID('Failed to read UID')
                logging.warning('Failed to read UID, please try swiping card again')
                continue
            self.cardRead(uid)

    def cardRead(self, uid):
        'Handle a card read, identified by `uid`'
        hexd = self.hexify(uid)
        logger.debug('cardRead: %r -> %r', uid, hexd)
        if hexd == self.last_card:
            #duplicate read, skip it
            return False

        self.last_card = hexd # store our fresh card so we dont double read it later
        if hexd in self.cards.keys():
            logger.info('Card %r recognised', hexd)
            #subprocess.Popen(['blink1-tool', '--rgb', '0x00,0xff,0x00', '--blink', '15'])
            self.b1.fade_rgb(0,255,100, 1000)
            self.b1.fade_rgb(0,255,100, 1000)
            self.b1.fade_rgb(0,255,100, 1000)
            self.b1.fade_rgb(0,255,100, 1000)
            logger.debug('Running configured commands for this card: %r', self.cards[hexd])
            for cmd in self.cards[hexd]:
                self.frontend.play_backend_uri(cmd)
        else:
            logger.info('Unknown card %r', hexd)
            #subprocess.Popen(['blink1-tool', '--rgb', '0xff,0x00,0x00', '--blink', '3'])
            self.b1.fade_rgb(255,0,100, 1000)
            self.b1.fade_rgb(255,0,100, 1000)
            self.b1.fade_rgb(255,0,100, 1000)
            self.b1.fade_rgb(255,0,100, 1000)

    def hexify(self, uid):
        return ''.join(['%02X' % d for d in uid])

    def stop(self):
        self.quitting = True
        self.atexit()


class RFIDFrontend(pykka.ThreadingActor, CoreListener):
    def __init__(self, config, core):
        super(RFIDFrontend, self).__init__(config, core)
        self.core = core
        self.config = config['rfid']
        self.rdr = RFIDReader(self)
        self.b1 = open_blink1()

    def on_start(self):
        logger.debug('extension startup')
        self.rdr.addCard( 'A4F0EB75CA', 'plex:album:13982')
        self.rdr.addCard( 'E299F475FA', 'plex:album:' ) # skarpe sanser
        self.rdr.addCard( 'F30BEF7562', 'plex:album:14051' ) # crazy frog
        self.rdr.addCard( '4707F175C4', 'plex:album:10014' ) # marcus martinus
        self.rdr.addCard( 'A612F47535', 'plex:album:10032' ) # kravitz
        self.rdr.addCard( '9D91F6A55F', 'plex:album:14068' ) # eventyrlig energi
        self.rdr.addCard( '5148ED7581', 'plex:track:7606' ) # merry xmas
        self.rdr.run()
        # TODO add preprogrammed color patterns for blink1

    def on_stop(self):
        logger.debug('extension teardown')
        try:
            self.b1.close()
            self.rdr.stop()
        except Exception as e:
            logger.exception(e)

    def playback_state_changed(self, old_state, new_state):
        """ Called whenever playback state is changed.

            MAY be implemented by actor.

            Parameters: 
            old_state (string from mopidy.core.PlaybackState field) – the state before the change
            new_state (string from mopidy.core.PlaybackState field) – the state after the change


            class mopidy.core.PlaybackState
                STOPPED = 'stopped'
                PLAYING = 'playing'
                PAUSED = 'paused'

        """
        logger.debug('Playback_state_changed(old, new): (%r, %r)', old_state, new_state)

        if new_state == PlaybackState.STOPPED:
            pass
        elif new_state == PlaybackState.PLAYING:
            pass
        elif new_state == PlaybackState.PAUSED:
            pass

    def play_backend_uri(self, uri):
        'takes a mopdiy uri, e.g. "plex:album:32323". look it up, and play what we find.'
    
        logging.info('play_backend_uri : "%r"', uri)
        hits = self.core.library.browse(uri).get()
        # browse(): Returns a list of mopidy.models.Ref objects for the directories and tracks at the given uri.
        logging.info('Got hits from browse(): %r', hits)
        if len(hits) == 0:
            # try track lookup
            hits = self.core.library.lookup(args.uri).get()
            logging.info('Got hits from lookup() : %r', hits)

        if len(hits) == 0:
            print('No hits for "{}"'.format(args.uri))
        else:
            self.core.tracklist.clear()
            logging.debug('got special uris: %r', [t.uri for t in hits])
            self.core.tracklist.add(uris=[t.uri for t in hits])
            self.core.playback.play().get()



