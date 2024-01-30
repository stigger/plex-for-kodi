# coding=utf-8

from lib import util

from . import kodigui
from . import optionsdialog
from . import busy
from lib.util import T


class SeasonsMixin:
    SEASONS_CONTROL_ATTR = "subItemListControl"

    THUMB_DIMS = {
        'show': {
            'main.thumb': util.scaleResolution(347, 518),
            'item.thumb': util.scaleResolution(174, 260)
        },
        'episode': {
            'main.thumb': util.scaleResolution(347, 518),
            'item.thumb': util.scaleResolution(198, 295)
        },
        'artist': {
            'main.thumb': util.scaleResolution(519, 519),
            'item.thumb': util.scaleResolution(215, 215)
        }
    }

    def _createListItem(self, mediaItem, obj):
        mli = kodigui.ManagedListItem(
            obj.title or '',
            thumbnailImage=obj.defaultThumb.asTranscodedImageURL(*self.THUMB_DIMS[mediaItem.type]['item.thumb']),
            data_source=obj
        )
        return mli

    def fillSeasons(self, mediaItem, update=False, seasonsFilter=None, selectSeason=None):
        seasons = mediaItem.seasons()
        if not seasons or (seasonsFilter and not seasonsFilter(seasons)):
            return False

        items = []
        idx = 0
        for season in seasons:
            if selectSeason and season == selectSeason:
                continue

            mli = self._createListItem(mediaItem, season)
            if mli:
                mli.setProperty('index', str(idx))
                mli.setProperty('thumb.fallback', 'script.plex/thumb_fallbacks/show.png')
                mli.setProperty('unwatched.count', not season.isWatched and str(season.unViewedLeafCount) or '')
                items.append(mli)
                idx += 1

        subItemListControl = getattr(self, self.SEASONS_CONTROL_ATTR)
        if update:
            subItemListControl.replaceItems(items)
        else:
            subItemListControl.reset()
            subItemListControl.addItems(items)

        return True


class DeleteMediaMixin:
    def delete(self, item=None):
        button = optionsdialog.show(
            T(32326, 'Really delete?'),
            T(32327, 'Are you sure you really want to delete this media?'),
            T(32328, 'Yes'),
            T(32329, 'No')
        )

        if button != 0:
            return

        if not self._delete(item=item or self.mediaItem):
            util.messageDialog(T(32330, 'Message'), T(32331, 'There was a problem while attempting to delete the media.'))
            return
        return True

    @busy.dialog()
    def _delete(self, item):
        success = item.delete()
        util.LOG('Media DELETE: {0} - {1}'.format(self.mediaItem, success and 'SUCCESS' or 'FAILED'))
        if success:
            self.doClose()
        return success


class RatingsMixin:
    def populateRatings(self, video, setProperty):
        def sanitize(src):
            return src.replace("themoviedb", "tmdb").replace('://', '/')

        if video.userRating:
            stars = str(int(round((video.userRating.asFloat() / 10) * 5)))
            setProperty('rating.stars', stars)

        audienceRating = video.audienceRating

        if video.rating or audienceRating:
            if video.rating:
                rating = video.rating
                if video.ratingImage.startswith('rottentomatoes:'):
                    rating = '{0}%'.format(int(rating.asFloat() * 10))

                setProperty('rating', rating)
                if video.ratingImage:
                    setProperty('rating.image', 'script.plex/ratings/{0}.png'.format(sanitize(video.ratingImage)))
            if audienceRating:
                if video.audienceRatingImage.startswith('rottentomatoes:'):
                    audienceRating = '{0}%'.format(int(audienceRating.asFloat() * 10))
                setProperty('rating2', audienceRating)
                if video.audienceRatingImage:
                    setProperty('rating2.image',
                                'script.plex/ratings/{0}.png'.format(sanitize(video.audienceRatingImage)))
        else:
            setProperty('rating', video.rating)
