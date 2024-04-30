# coding=utf-8

import os
import json
import time
import copy

from kodi_six import xbmcvfs

from . util import translatePath, ADDON, ERROR, DEBUG_LOG, LOG


class DataCacheManager(object):
    # store arbitrary data in JSON on disk
    DATA_CACHES_VERSION = 1
    DATA_CACHES = {
        "general": {}
    }
    DC_LAST_UPDATE = None
    DC_PATH = os.path.join(translatePath(ADDON.getAddonInfo("profile")), "data_cache.json")

    def __init__(self):
        if xbmcvfs.exists(self.DC_PATH):
            try:
                f = xbmcvfs.File(self.DC_PATH)
                d = f.read()
                f.close()

                tdc = json.loads(d)
                if tdc["general"].get("version", 0) < self.DATA_CACHES_VERSION:
                    tdc["general"]["version"] = self.DATA_CACHES_VERSION
                    # this is where we migrate

                self.DATA_CACHES.update(tdc)
                self.DC_LAST_UPDATE = self.DATA_CACHES["general"]["updated"]
            except:
                ERROR("Couldn't read data_cache.json")
                self.DATA_CACHES["general"]["updated"] = time.time()
                self.storeDataCache()

    def getCacheData(self, context, identifier):
        ret = self.DATA_CACHES.get(context, {}).get(identifier, {})
        if "data" in ret and ret["data"]:
            self.DATA_CACHES[context][identifier]["last_access"] = time.time()
            return ret["data"]

    def setCacheData(self, context, identifier, value):
        if context not in self.DATA_CACHES:
            self.DATA_CACHES[context] = {}
        if identifier not in self.DATA_CACHES[context]:
            self.DATA_CACHES[context][identifier] = {}
        self.DATA_CACHES[context][identifier]["data"] = value
        t = time.time()
        self.DATA_CACHES["general"]["updated"] = t
        self.DATA_CACHES[context][identifier]["last_access"] = t

    def dataCacheCleanup(self):
        d = copy.deepcopy(self.DATA_CACHES)
        t = time.time()
        for context, identifiers in d.items():
            if context != "general":
                for identifier, iddata in identifiers.items():
                    # clean up anything not accessed during the last 30 days
                    if iddata["last_access"] < t - 2592000:
                        DEBUG_LOG("Clearing cached data for: {}: {}".format(context, identifier))
                        del self.DATA_CACHES[context][identifier]

    def storeDataCache(self):
        if self.DATA_CACHES and self.DC_LAST_UPDATE != self.DATA_CACHES["general"]["updated"]:
            try:
                dcf = xbmcvfs.File(self.DC_PATH, "w")
                self.dataCacheCleanup()
                dcf.write(json.dumps(self.DATA_CACHES))
                dcf.close()
                LOG("Data cache written to: addon_data/script.plexmod/data_cache.json")
            except:
                ERROR("Couldn't write data_cache.json")


dcm = DataCacheManager()
