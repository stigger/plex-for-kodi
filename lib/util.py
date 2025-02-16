# -*- coding: utf-8 -*-
from __future__ import absolute_import

import gc
import sys
import re
import binascii
import json
import threading
import math
import time
import datetime
import contextlib
import types

import unicodedata

import six.moves.urllib.request, six.moves.urllib.parse, six.moves.urllib.error
import six
import os
import struct
import requests

import plexnet.util

from .kodijsonrpc import rpc
from kodi_six import xbmc
from kodi_six import xbmcgui
from kodi_six import xbmcaddon
from kodi_six import xbmcvfs

from . import colors
# noinspection PyUnresolvedReferences
from .exceptions import NoDataException
from plexnet import signalsmixin

DEBUG = True
_SHUTDOWN = False

ADDON = xbmcaddon.Addon()

SETTINGS_LOCK = threading.Lock()

_build = None
# buildversion looks like: XX.X[-TAG] (a+.b+.c+) (.+); there are kodi builds that don't set the build version
sys_ver = xbmc.getInfoLabel('System.BuildVersion')
_ver = sys_ver

try:
    if ' ' in sys_ver and '(' in sys_ver:
        _ver, _build = sys_ver.split()[:2]

    _splitver = _ver.split(".")
    KODI_VERSION_MAJOR, KODI_VERSION_MINOR = int(_splitver[0].split("-")[0].strip()), \
                                             int(_splitver[1].split(" ")[0].split("-")[0].strip())
except:
    xbmc.log('script.plex: Couldn\'t determine Kodi version, assuming 19.4. Got: {}'.format(sys_ver))
    # assume something "old"
    KODI_VERSION_MAJOR = 19
    KODI_VERSION_MINOR = 4

_bmajor, _bminor, _bpatch = (KODI_VERSION_MAJOR, KODI_VERSION_MINOR, 0)
parsedBuild = False
if _build:
    try:
        _bmajor, _bminor, _bpatch = _build[1:-1].split(".")
        parsedBuild = True
    except:
        pass
if not parsedBuild:
    xbmc.log('script.plex: Couldn\'t determine build version, falling back to Kodi version', xbmc.LOGINFO)

# calculate a comparable build number
KODI_BUILD_NUMBER = int("{0}{1:02d}{2:03d}".format(_bmajor, int(_bminor), int(_bpatch)))
xbmc.log('script.plex: Kodi {0}.{1} (build {2})'.format(KODI_VERSION_MAJOR, KODI_VERSION_MINOR, KODI_BUILD_NUMBER),
         xbmc.LOGINFO)


if KODI_VERSION_MAJOR > 18:
    translatePath = xbmcvfs.translatePath
else:
    translatePath = xbmc.translatePath

PROFILE = translatePath(ADDON.getAddonInfo('profile'))


def getChannelMapping():
    data = rpc.Settings.GetSettings(filter={"section": "system", "category": "audio"})["settings"]
    return list(filter(lambda i: i["id"] == "audiooutput.channels", data))[0]["options"]


# retrieve labels for mapping audio channel settings values
try:
    CHANNELMAPPING = dict((t["value"], t["label"]) for t in getChannelMapping())
except:
    CHANNELMAPPING = None


def getLanguageCode(add_def=None):
    data = rpc.Settings.GetSettingValue(setting='locale.language')['value'].replace('resource.language.', '')
    lang = ""
    if "_" in data:
        base, variant = data.split("_")
        lang += "{}-{},{}".format(base, variant.upper(), base)
    else:
        lang = data
    if add_def and lang not in add_def:
        lang += ",{}".format(add_def)
    return lang


try:
    ACCEPT_LANGUAGE_CODE = getLanguageCode(add_def='en-US,en')
except:
    ACCEPT_LANGUAGE_CODE = 'en-US,en'


def getSetting(key, default=None):
    with SETTINGS_LOCK:
        setting = ADDON.getSetting(key)
        return _processSetting(setting, default)


def getUserSetting(key, default=None):
    if not plexnet.util.ACCOUNT:
        return default

    key = '{}.{}'.format(key, plexnet.util.ACCOUNT.ID)
    with SETTINGS_LOCK:
        setting = ADDON.getSetting(key)
        return _processSetting(setting, default)


def _processSetting(setting, default):
    if not setting:
        return default
    if isinstance(default, bool):
        return setting.lower() == 'true'
    elif isinstance(default, float):
        return float(setting)
    elif isinstance(default, int):
        return int(float(setting or 0))
    elif isinstance(default, list):
        if setting:
            return json.loads(binascii.unhexlify(setting))
        else:
            return default

    return setting


class AddonSettings(object):
    """
    @DynamicAttrs
    """

    _proxiedSettings = (
        ("debug", False),
        ("kodi_skip_stepping", False),
        ("auto_seek", True),
        ("auto_seek_delay", 1),
        ("dynamic_timeline_seek", False),
        ("fast_back", True),
        ("dynamic_backgrounds", True),
        ("background_art_blur_amount2", 0),
        ("background_art_opacity_amount2", 20),
        ("screensaver_quiz", False),
        ("postplay_always", False),
        ("postplay_timeout", 16),
        ("skip_intro_button_timeout", 10),
        ("skip_credits_button_timeout", 10),
        ("playlist_visit_media", False),
        ("intro_skip_early", False),
        ("show_media_ends_info", True),
        ("show_media_ends_label", True),
        ("background_colour", None),
        ("skip_intro_button_show_early_threshold1", 70),
        ("requests_timeout", 5.0),
        ("local_reach_timeout", 10),
        ("auto_skip_offset", 2.5),
        ("conn_check_timeout", 2.5),
        ("postplayCancel", True),
        ("skip_marker_timer_cancel", True),
        ("skip_marker_timer_immediate", False),
        ("low_drift_timer", True),
        ("player_show_buffer", True),
        ("buffer_wait_max", 120),
        ("buffer_insufficient_wait", 10),
        ("continue_use_thumb", True),
        ("use_bg_fallback", False),
        ("dbg_crossfade", True),
        ("subtitle_use_extended_title", True),
        ("poster_resolution_scale_perc", 100),
        ("consecutive_video_pb_wait", 0.0),
        ("retrieve_all_media_up_front", False),
        ("library_chunk_size", 240),
        ("verify_mapped_files", True),
        ("episode_no_spoiler_blur", 16),
        ("ignore_docker_v4", True),
        ("cache_home_users", True),
        ("intro_marker_max_offset", 600),
    )

    def __init__(self):
        # register every known setting camelCased as an attribute to this instance
        for setting, default in self._proxiedSettings:
            name_split = setting.split("_")
            setattr(self, name_split[0] + ''.join(x.capitalize() or '_' for x in name_split[1:]),
                    getSetting(setting, default))


addonSettings = AddonSettings()


def LOG(msg, *args, **kwargs):
    if args:
        # resolve dynamic args
        msg = msg.format(*[arg() if isinstance(arg, types.FunctionType) else arg for arg in args])

    level = kwargs.pop("level", xbmc.LOGINFO)

    if kwargs:
        # resolve dynamic kwargs
        msg = msg.format(**dict((k, v()) if isinstance(v, types.FunctionType) else v for k, v in kwargs.items()))
    xbmc.log('script.plex: {0}'.format(msg), level)


def DEBUG_LOG(msg, *args, **kwargs):
    if _SHUTDOWN:
        return

    if not addonSettings.debug and not xbmc.getCondVisibility('System.GetBool(debug.showloginfo)'):
        return

    LOG(msg, *args, **kwargs)


def ERROR(txt='', hide_tb=False, notify=False, time_ms=3000):
    short = str(sys.exc_info()[1])
    if hide_tb:
        xbmc.log('script.plex: ERROR: {0} - {1}'.format(txt, short), xbmc.LOGERROR)
        return short

    import traceback
    tb = traceback.format_exc()
    xbmc.log("_________________________________________________________________________________", xbmc.LOGERROR)
    xbmc.log('script.plex: ERROR: ' + txt, xbmc.LOGERROR)
    for l in tb.splitlines():
        xbmc.log('    ' + l, xbmc.LOGERROR)
    xbmc.log("_________________________________________________________________________________", xbmc.LOGERROR)
    xbmc.log("`", xbmc.LOGERROR)
    if notify:
        showNotification('ERROR: {0}'.format(txt or short), time_ms=time_ms)
    return short


def TEST(msg):
    xbmc.log('---TEST: {0}'.format(msg), xbmc.LOGINFO)


class UtilityMonitor(xbmc.Monitor, signalsmixin.SignalsMixin):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self, *args, **kwargs)
        signalsmixin.SignalsMixin.__init__(self)

    def watchStatusChanged(self):
        self.trigger('changed.watchstatus')

    def actionStop(self):
        self.stopPlayback()

    def actionQuit(self):
        LOG('OnSleep: Exit Kodi')
        xbmc.executebuiltin('Quit')

    def actionReboot(self):
        LOG('OnSleep: Reboot')
        xbmc.restart()

    def actionShutdown(self):
        LOG('OnSleep: Shutdown')
        xbmc.shutdown()

    def actionHibernate(self):
        LOG('OnSleep: Hibernate')
        xbmc.executebuiltin('Hibernate')

    def actionSuspend(self):
        LOG('OnSleep: Suspend')
        xbmc.executebuiltin('Suspend')

    def actionCecstandby(self):
        LOG('OnSleep: CEC Standby')
        xbmc.executebuiltin('CECStandby')

    def actionLogoff(self):
        LOG('OnSleep: Sign Out')
        xbmc.executebuiltin('System.LogOff')

    def onNotification(self, sender, method, data):
        LOG("Notification: {} {} {}".format(sender, method, data))
        if sender == 'script.plexmod' and method.endswith('RESTORE'):
            from .windows import kodigui
            if not kodigui.BaseFunctions.lastWinID:
                ERROR("Addon never properly started, can't reactivate")
                setGlobalProperty('stop_running', '1')
                return
            if kodigui.BaseFunctions.lastWinID > 13000:
                reInitAddon()
                xbmc.executebuiltin('ActivateWindow({0})'.format(kodigui.BaseFunctions.lastWinID))
            else:
                ERROR("Addon never properly started, can't reactivate")
                setGlobalProperty('stop_running', '1')
                return

        elif sender == "xbmc" and method == "System.OnSleep":
            if getSetting('action_on_sleep', "none") != "none":
                getattr(self, "action{}".format(getSetting('action_on_sleep', "none").capitalize()))()
            self.trigger('system.sleep')

        elif sender == "xbmc" and method == "System.OnWake":
            self.trigger('system.wakeup')

    def stopPlayback(self):
        LOG('Monitor: Stopping media playback')
        xbmc.Player().stop()

    def onScreensaverActivated(self):
        DEBUG_LOG("Monitor: OnScreensaverActivated")
        self.trigger('screensaver.activated')
        if getSetting('player_stop_on_screensaver', True) and xbmc.Player().isPlayingVideo():
            self.stopPlayback()

    def onScreensaverDeactivated(self):
        DEBUG_LOG("Monitor: OnScreensaverDeactivated")
        self.trigger('screensaver.deactivated')

    def onDPMSActivated(self):
        DEBUG_LOG("Monitor: OnDPMSActivated")
        self.trigger('dpms.activated')
        #self.stopPlayback()

    def onDPMSDeactivated(self):
        DEBUG_LOG("Monitor: OnDPMSDeactivated")
        self.trigger('dpms.deactivated')
        #self.stopPlayback()

    def onSettingsChanged(self):
        """ unused stub, but works if needed """
        pass


MONITOR = UtilityMonitor()


def T(ID, eng=''):
    return ADDON.getLocalizedString(ID)


hasCustomBGColour = False
if KODI_VERSION_MAJOR > 18:
    hasCustomBGColour = not addonSettings.dynamicBackgrounds and addonSettings.backgroundColour and \
                        addonSettings.backgroundColour != "-"


def getAdvancedSettings():
    # yes, global, hang me!
    global addonSettings
    addonSettings = AddonSettings()


def reInitAddon():
    global ADDON
    # reinit the ADDON reference so we get the updated addon settings
    ADDON = xbmcaddon.Addon()
    getAdvancedSettings()
    populateTimeFormat()


def setSetting(key, value):
    with SETTINGS_LOCK:
        value = _processSettingForWrite(value)
        ADDON.setSetting(key, value)


def _processSettingForWrite(value):
    if isinstance(value, list):
        value = binascii.hexlify(json.dumps(value))
    elif isinstance(value, bool):
        value = value and 'true' or 'false'
    return str(value)


def setGlobalProperty(key, val, base='script.plex.{0}'):
    xbmcgui.Window(10000).setProperty(base.format(key), val)


def setGlobalBoolProperty(key, boolean, base='script.plex.{0}'):
    xbmcgui.Window(10000).setProperty(base.format(key), boolean and '1' or '')


def getGlobalProperty(key):
    return xbmc.getInfoLabel('Window(10000).Property(script.plex.{0})'.format(key))


def showNotification(message, time_ms=3000, icon_path=None, header=ADDON.getAddonInfo('name')):
    try:
        icon_path = icon_path or translatePath(ADDON.getAddonInfo('icon'))
        xbmc.executebuiltin('Notification({0},{1},{2},{3})'.format(header, message, time_ms, icon_path))
    except RuntimeError:  # Happens when disabling the addon
        LOG(message)


def videoIsPlaying():
    return xbmc.getCondVisibility('Player.HasVideo')


def messageDialog(heading='Message', msg=''):
    from .windows import optionsdialog
    optionsdialog.show(heading, msg, 'OK')


def showTextDialog(heading, text):
    t = TextBox()
    t.setControls(heading, text)


def sortTitle(title):
    return title.startswith('The ') and title[4:] or title


def durationToText(seconds):
    """
    Converts seconds to a short user friendly string
    Example: 143 -> 2m 23s
    """
    days = int(seconds / 86400000)
    if days:
        return '{0} day{1}'.format(days, days > 1 and 's' or '')
    left = seconds % 86400000
    hours = int(left / 3600000)
    if hours:
        hours = '{0} hr{1} '.format(hours, hours > 1 and 's' or '')
    else:
        hours = ''
    left = left % 3600000
    mins = int(left / 60000)
    if mins:
        return hours + '{0} min{1}'.format(mins, mins > 1 and 's' or '')
    elif hours:
        return hours.rstrip()
    secs = int(left % 60000)
    if secs:
        secs /= 1000
        return '{0} sec{1}'.format(secs, secs > 1 and 's' or '')
    return '0 seconds'


def durationToShortText(ms, shortHourMins=False):
    """
    Converts seconds to a short user friendly string
    Example: 143 -> 2m 23s
    """
    days = int(ms / 86400000)
    if days:
        return '{0} d'.format(days)
    left = ms % 86400000
    hours = int(left / 3600000)
    if hours:
        hours_s = '{0} h '.format(hours)
    else:
        hours_s = ''
    left = left % 3600000
    mins = int(left / 60000)
    if mins:
        if shortHourMins and hours:
            return '{0}:{1} h'.format(hours, mins)
        return hours_s + '{0} m'.format(mins)
    elif hours_s:
        return hours_s.rstrip()
    secs = int(left % 60000)
    if secs:
        secs /= 1000
        return '{0} s'.format(secs)
    return '0 s'


def cleanLeadingZeros(text):
    if not text:
        return ''
    return re.sub(r'(?<= )0(\d)', r'\1', text)


def removeDups(dlist):
    return [ii for n, ii in enumerate(dlist) if ii not in dlist[:n]]


SIZE_NAMES = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")


def simpleSize(size):
    """
    Converts bytes to a short user friendly string
    Example: 12345 -> 12.06 KB
    """
    s = 0
    if size > 0:
        i = int(math.floor(math.log(size, 1024)))
        p = math.pow(1024, i)
        s = round(size / p, 2)
    if (s > 0):
        return '%s %s' % (s, SIZE_NAMES[i])
    else:
        return '0B'


def timeDisplay(ms, cutHour=False):
    h = ms / 3600000
    m = (ms % 3600000) / 60000
    s = (ms % 60000) / 1000
    if h >= 1 or not cutHour:
        return '{0:0>2}:{1:0>2}:{2:0>2}'.format(int(h), int(m), int(s))
    return '{0:0>2}:{1:0>2}'.format(int(m), int(s))


def simplifiedTimeDisplay(ms):
    left, right = timeDisplay(ms).rsplit(':', 1)
    left = left.lstrip('0:') or '0'
    return left + ':' + right


def shortenText(text, size):
    if len(text) < size:
        return text

    return u'{0}\u2026'.format(text[:size - 1])


def scaleResolution(w, h, by=None):
    if by is None:
        by = addonSettings.posterResolutionScalePerc

    if 0 < by != 100.0:
        px = w * h * (by / 100.0)
        wratio = h / float(w)
        hratio = w / float(h)
        return int(round((px / wratio) ** .5)), int(round((px / hratio) ** .5))
    return w, h


SPOILER_ALLOWED_GENRES = ("Reality", "Game Show", "Documentary", "Sport")


class TextBox:
    # constants
    WINDOW = 10147
    CONTROL_LABEL = 1
    CONTROL_TEXTBOX = 5

    def __init__(self, *args, **kwargs):
        # activate the text viewer window
        xbmc.executebuiltin("ActivateWindow(%d)" % (self.WINDOW, ))
        # get window
        self.win = xbmcgui.Window(self.WINDOW)
        # give window time to initialize
        xbmc.sleep(1000)

    def setControls(self, heading, text):
        # set heading
        self.win.getControl(self.CONTROL_LABEL).setLabel(heading)
        # set text
        self.win.getControl(self.CONTROL_TEXTBOX).setText(text)


class SettingControl:
    def __init__(self, setting, log_display, disable_value=''):
        self.setting = setting
        self.logDisplay = log_display
        self.disableValue = disable_value
        self._originalMode = None
        self.store()

    def disable(self):
        rpc.Settings.SetSettingValue(setting=self.setting, value=self.disableValue)
        DEBUG_LOG('{0}: DISABLED'.format(self.logDisplay))

    def set(self, value):
        rpc.Settings.SetSettingValue(setting=self.setting, value=value)
        DEBUG_LOG('{0}: SET={1}'.format(self.logDisplay, value))

    def store(self):
        try:
            self._originalMode = rpc.Settings.GetSettingValue(setting=self.setting).get('value')
            DEBUG_LOG('{0}: Mode stored ({1})'.format(self.logDisplay, self._originalMode))
        except:
            ERROR()

    def restore(self):
        if self._originalMode is None:
            return
        rpc.Settings.SetSettingValue(setting=self.setting, value=self._originalMode)
        DEBUG_LOG('{0}: RESTORED'.format(self.logDisplay))

    @contextlib.contextmanager
    def suspend(self):
        self.disable()
        yield
        self.restore()

    @contextlib.contextmanager
    def save(self):
        yield
        self.restore()


def timeInDayLocalSeconds():
    now = datetime.datetime.now()
    sod = datetime.datetime(year=now.year, month=now.month, day=now.day)
    sod = int(time.mktime(sod.timetuple()))
    return int(time.time() - sod)


def getKodiSkipSteps():
    try:
        return rpc.Settings.GetSettingValue(setting="videoplayer.seeksteps")["value"]
    except:
        return


def getKodiSlideshowInterval():
    try:
        return rpc.Settings.GetSettingValue(setting="slideshow.staytime")["value"]
    except:
        return 3


kodiSkipSteps = getKodiSkipSteps()
slideshowInterval = getKodiSlideshowInterval()


CRON = None


class CronReceiver():
    def tick(self):
        pass

    def halfHour(self):
        pass

    def day(self):
        pass


class Cron(threading.Thread):
    def __init__(self, interval):
        threading.Thread.__init__(self, name='CRON')
        self.stopped = threading.Event()
        self.force = threading.Event()
        self.interval = interval
        self._lastHalfHour = self._getHalfHour()
        self._receivers = []

        global CRON

        CRON = self

    def __enter__(self):
        self.start()
        DEBUG_LOG('Cron started')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        self.join()

    def _wait(self):
        ct = 0
        while ct < self.interval:
            xbmc.sleep(100)
            ct += 0.1
            if self.force.isSet():
                self.force.clear()
                return True
            if MONITOR.abortRequested() or self.stopped.isSet():
                return False
        return True

    def forceTick(self):
        self.force.set()

    def stop(self):
        self.stopped.set()

    def run(self):
        while self._wait():
            self._tick()
        DEBUG_LOG('Cron stopped')

    def _getHalfHour(self):
        tid = timeInDayLocalSeconds() / 60
        return tid - (tid % 30)

    def _tick(self):
        receivers = list(self._receivers)
        receivers = self._halfHour(receivers)
        for r in receivers:
            try:
                r.tick()
            except:
                ERROR()

    def _halfHour(self, receivers):
        hh = self._getHalfHour()
        if hh == self._lastHalfHour:
            return receivers
        try:
            receivers = self._day(receivers, hh)
            ret = []
            for r in receivers:
                try:
                    if not r.halfHour():
                        ret.append(r)
                except:
                    ret.append(r)
                    ERROR()
            return ret
        finally:
            self._lastHalfHour = hh

    def _day(self, receivers, hh):
        if hh >= self._lastHalfHour:
            return receivers
        ret = []
        for r in receivers:
            try:
                if not r.day():
                    ret.append(r)
            except:
                ret.append(r)
                ERROR()
        return ret

    def registerReceiver(self, receiver):
        if receiver not in self._receivers:
            DEBUG_LOG('Cron: Receiver added: {0}'.format(receiver))
            self._receivers.append(receiver)

    def cancelReceiver(self, receiver):
        if receiver in self._receivers:
            DEBUG_LOG('Cron: Receiver canceled: {0}'.format(receiver))
            self._receivers.pop(self._receivers.index(receiver))


def getTimeFormat():
    """
    Generic:
    Use locale.timeformat setting to get and make use of the format.

    Possible values:
    HH:mm:ss -> %H:%M:%S
    regional -> legacy
    H:mm:ss  -> %-H:%M:%S

    Legacy: Not necessarily true for Omega?; regional spices things up (depending on Kodi version?)
    Get global time format.
    Kodi's time format handling is weird, as they return incompatible formats for strftime.
    %H%H can be returned for manually set zero-padded values, in case of a regional zero-padded hour component,
    only %H is returned.

    For now, sail around that by testing the current time for padded hour values.

    Tests of the values returned by xbmc.getRegion("time") as of Kodi Nexus (I believe):
    %I:%M:%S %p = h:mm:ss, non-zero-padded, 12h PM
    %I:%M:%S = 12h, h:mm:ss, non-zero-padded, regional
    %I%I:%M:%S = 12h, zero padded, hh:mm:ss
    %H%H:%M:%S = 24h, zero padded, hh:mm:ss
    %H:%M:%S = 24h, zero padded, regional, regional (central europe)

    :return: tuple of strftime-compatible format, boolean padHour
    """

    fmt = None
    nonPadHF = "%-H" if sys.platform != "win32" else "%#H"
    nonPadIF = "%-I" if sys.platform != "win32" else "%#I"

    try:
        fmt = rpc.Settings.GetSettingValue(setting="locale.timeformat")["value"]
    except:
        DEBUG_LOG("Couldn't get locale.timeformat setting, falling back to legacy detection")

    if fmt and fmt != "regional":
        # HH = padded 24h
        # hh = padded 12h
        # H = unpadded 24h
        # h = unpadded 12h

        # handle non-padded hour first
        if fmt.startswith("H:") or fmt.startswith("h:"):
            adjustedFmt = fmt.replace("H", nonPadHF).replace("h", nonPadIF)
        else:
            adjustedFmt = fmt.replace("HH", "%H").replace("hh", "%I")

        padHour = adjustedFmt.startswith("%H") or adjustedFmt.startswith("%I")

    else:
        DEBUG_LOG("Regional time format detected, falling back to legacy detection of hour-padding")
        # regional is weirdly always unpadded (unless the broken %H%H/%I%I notation is used
        origFmt = xbmc.getRegion('time')

        adjustedFmt = origFmt.replace("%H%H", "%H").replace("%I%I", "%I")

        # Checking for %H%H or %I%I only would be the obvious way here to determine whether the hour should be padded,
        # but the formats returned for regional settings with padding might only have %H in them.
        # Use a fallback (unreliable).
        currentTime = xbmc.getInfoLabel('System.Time')
        padHour = "%H%H" in origFmt or "%I%I" in origFmt or (currentTime[0] == "0" and currentTime[1] != ":")

    # Kodi Omega on Android seems to have borked the regional format returned separately
    # (not happening on Windows at least). Format returned can be "%H:mm:ss", which is incompatible with strftime; fix.
    adjustedFmt = adjustedFmt.replace("mm", "%M").replace("ss", "%S").replace("xx", "%p")
    adjustedFmtKN = adjustedFmt.replace("%M", "mm").replace("%H", "hh").replace("%I", "h").replace("%S", "ss").\
        replace("%p", "xx").replace(nonPadIF, "h").replace(nonPadHF, "h")

    return adjustedFmt,  adjustedFmtKN, padHour


timeFormat, timeFormatKN, padHour = getTimeFormat()


def getShortDateFormat():
    try:
        return (rpc.Settings.GetSettingValue(setting="locale.shortdateformat")["value"]
                .replace("DD", "%d").replace("MM", "%m").replace("YYYY", "%Y"))
    except:
        DEBUG_LOG("Couldn't get locale.shortdateformat setting, falling back to MM/DD/YYYY")
        return "%d/%m/%Y"


shortDF = getShortDateFormat()

DEF_THEME = "modern-colored"
THEME_VERSION = 3


def applyTheme(theme=None):
    """
    Dynamically build script-plex-seek_dialog.xml by combining a player button template with
    script-plex-seek_dialog_skeleton.xml
    """
    theme = theme or getSetting('theme', DEF_THEME)
    skel = os.path.join(ADDON.getAddonInfo('path'), "resources", "skins", "Main", "1080i",
                        "script-plex-seek_dialog_skeleton.xml")
    if theme == "custom":
        btnTheme = os.path.join(ADDON.getAddonInfo("profile"), "templates",
                                "seek_dialog_buttons_custom.xml")
        customSkel = os.path.join(ADDON.getAddonInfo("profile"), "templates",
                                  "script-plex-seek_dialog_skeleton_custom.xml")
        if xbmcvfs.exists(customSkel):
            skel = customSkel
    else:
        btnTheme = os.path.join(ADDON.getAddonInfo('path'), "resources", "skins", "Main", "1080i", "templates",
                                "seek_dialog_buttons_{}.xml".format(theme))

    if not xbmcvfs.exists(btnTheme):
        LOG("Theme {} doesn't exist, falling back to modern".format(theme))
        setSetting('theme', DEF_THEME)
        return applyTheme(DEF_THEME)

    try:
        # read skeleton
        f = xbmcvfs.File(skel)
        skelData = f.read()
        f.close()
    except:
        ERROR("Couldn't find {}".format("script-plex-seek_dialog_skeleton.xml"))
    else:
        try:
            # read button theme
            f = xbmcvfs.File(btnTheme)
            btnData = f.read()
            f.close()
        except:
            ERROR("Couldn't find {}".format("seek_dialog_buttons_{}.xml".format(theme)))
        else:
            # combine both
            finalXML = skelData.replace('<!-- BUTTON_INCLUDE -->', btnData)
            try:
                # write final file
                f = xbmcvfs.File(os.path.join(ADDON.getAddonInfo('path'), "resources", "skins", "Main", "1080i",
                                 "script-plex-seek_dialog.xml"), "w")
                f.write(finalXML)
                f.close()
            except:
                ERROR("Couldn't write script-plex-seek_dialog.xml")
            else:
                LOG('Using theme: {}'.format(theme))


# apply theme if version changed
theme = getSetting('theme', DEF_THEME)
curThemeVer = getSetting('theme_version', 0)
if curThemeVer < THEME_VERSION:
    setSetting('theme_version', THEME_VERSION)
    # apply seekdialog button theme
    applyTheme(theme)

# apply theme if seek_dialog xml missing
if not xbmcvfs.exists(os.path.join(ADDON.getAddonInfo('path'), "resources", "skins", "Main", "1080i",
                                   "script-plex-seek_dialog.xml")):
    applyTheme(theme)


# get mounts
KODI_SOURCES = []


def getKodiSources():
    try:
        data = rpc.Files.GetSources(media="files")["sources"]
    except:
        LOG("Couldn't parse Kodi sources")
    else:
        for d in data:
            f = d["file"]
            if f.startswith("smb://") or f.startswith("nfs://") or f.startswith("/") or ':\\\\' in f:
                KODI_SOURCES.append(d)
        LOG("Parsed {} Kodi sources: {}".format(len(KODI_SOURCES), KODI_SOURCES))


if getSetting('path_mapping', True):
    getKodiSources()


def populateTimeFormat():
    global timeFormat, timeFormatKN, padHour
    timeFormat, timeFormatKN, padHour = getTimeFormat()


def getPlatform():
    for key in [
        'System.Platform.Android',
        'System.Platform.Linux.RaspberryPi',
        'System.Platform.Linux',
        'System.Platform.Windows',
        'System.Platform.OSX',
        'System.Platform.IOS',
        'System.Platform.Darwin',
        'System.Platform.ATV2'
    ]:
        if xbmc.getCondVisibility(key):
            return key.rsplit('.', 1)[-1]


def getRunningAddons():
    try:
        return xbmcvfs.listdir('addons://running/')[1]
    except:
        return []


def getUserAddons():
    try:
        return xbmcvfs.listdir('addons://user/all')[1]
    except:
        return []


USER_ADDONS = getUserAddons()


SLUGIFY_RE1 = re.compile(r'[^\w\s-]')
SLUGIFY_RE2 = re.compile(r'[-\s]+')


def slugify(value):
    """
    Converts to lowercase, removes non-word characters (alphanumerics and
    underscores) and converts spaces to hyphens. Also strips leading and
    trailing whitespace.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = SLUGIFY_RE1.sub('', value).strip().lower()
    return SLUGIFY_RE2.sub('-', value)


def getProgressImage(obj, perc=None, view_offset=None):
    if not obj and not perc:
        return ''

    if obj:
        if not view_offset:
            view_offset = obj.get('viewOffset') and obj.viewOffset.asInt()
        if not view_offset or not obj.get('duration'):
            return ''
        pct = int((view_offset / obj.duration.asFloat()) * 100)
    else:
        pct = perc
    pct = pct - pct % 2  # Round to even number - we have even numbered progress only
    pct = max(pct, 2)
    return 'script.plex/progress/{0}.png'.format(pct)


def backgroundFromArt(art, width=1920, height=1080, background=colors.noAlpha.Background):
    if not art:
        return
    return art.asTranscodedImageURL(
        width, height,
        blur=addonSettings.backgroundArtBlurAmount2,
        opacity=addonSettings.backgroundArtOpacityAmount2,
        background=background
    )


def trackIsPlaying(track):
    return xbmc.getCondVisibility('String.StartsWith(MusicPlayer.Comment,{0})'.format('PLEX-{0}:'.format(track.ratingKey)))


def addURLParams(url, params):
        if '?' in url:
            url += '&'
        else:
            url += '?'
        url += six.moves.urllib.parse.urlencode(params)
        return url


OSS_CHUNK = 65536


def getOpenSubtitlesHash(size, url):
    long_long_format = "q"  # long long
    byte_size = struct.calcsize(long_long_format)
    hash_ = filesize = size
    if filesize < OSS_CHUNK * 2:
        return

    buffer = b''
    for _range in ((0, OSS_CHUNK), (filesize-OSS_CHUNK, filesize)):
        try:
            r = requests.get(url, headers={"range": "bytes={0}-{1}".format(*_range)}, stream=True)
        except:
            return ''
        buffer += r.raw.read(OSS_CHUNK)

    for x in range(int(OSS_CHUNK / byte_size) * 2):
        size = x * byte_size
        (l_value,) = struct.unpack(long_long_format, buffer[size:size + byte_size])
        hash_ += l_value
        hash_ = hash_ & 0xFFFFFFFFFFFFFFFF

    return format(hash_, "016x")


def ensureHome():
    if xbmcgui.getCurrentWindowId() != 10000:
        LOG("Switching to home screen before starting addon")
        xbmc.executebuiltin('ActivateWindow(home)')
        ct = 0
        while xbmcgui.getCurrentWindowId() != 10000 and ct <= 50:
            xbmc.Monitor().waitForAbort(0.1)
            ct += 1
        if ct > 50:
            DEBUG_LOG("Still active window: %s" % xbmcgui.getCurrentWindowId())


def garbageCollect():
    gc.collect(2)


def shutdown():
    global MONITOR, ADDON, T, _SHUTDOWN
    _SHUTDOWN = True
    del MONITOR
    del T
    del ADDON
