import time
from datetime import date, datetime, timedelta
from logging import getLogger
from typing import Dict, List, Union

import pytz
import tweepy

from .constants import API_COUNTS, FULL_TEXT_TWEET_MODE, SEARCH_API_PATH, TODAY_EXCLUDED
from .limits import get_rate_limit_reset_time, is_rate_limit
from .processors import make_weekday

logger = getLogger(__name__)


def search_tweets(
    api: tweepy.API, search_query: str, limit: int, timezone
) -> List[Dict]:
    """ツイートを検索する

    :param api: tweepy.API
    :param search_query: 検索クエリ
    :param timezone: timezoneオブジェクト
    :param limit: 検索件数の上限、この値に達したら結果を返す
    """

    _now = datetime.now(timezone)
    _today = _now.date()

    # TwitterAPIの無料プランで取得可能な一番古い日付は24時間分取得できていないため、日付軸分析、時間軸分析でノイズになり得る。
    # make_search_from_queryで分析対象から除外しておく。
    _query = search_query
    _query += " " + _make_search_from_query(timezone=timezone)
    if TODAY_EXCLUDED:
        # 当日除外が指定されていた場合はTo日付を指定
        _query += " " + _make_excluded_today_search_to_query(timezone=timezone)

    tweets = []
    next_max_tweet_id = None
    limited = False
    while True:
        if is_rate_limit(api, api_path=SEARCH_API_PATH):
            reset_time = get_rate_limit_reset_time(api, api_path=SEARCH_API_PATH)
            logger.info(f"アクセス上限のため処理休止中({reset_time}秒)..")
            time.sleep(reset_time)

        _tweets = []
        try:
            _tweets = api.search(
                q=search_query,
                tweet_mode=FULL_TEXT_TWEET_MODE,
                count=API_COUNTS[SEARCH_API_PATH],
                max_id=next_max_tweet_id,
            )
        except tweepy.RateLimitError:
            logger.info("アクセス上限のため処理休止中(15分)..")
            time.sleep(15 * 60)

        # 取得するツイートがなくなった場合に処理終了
        if len(_tweets) == 0:
            break

        for t in _tweets:
            if timezone == "UTC":
                dt = t.created_at
            else:
                dt = _convert_timezone(t.created_at, timezone=timezone)

            tweets.append(
                {
                    "tweeted_dt": dt,
                    "tweeted_date": dt.date(),
                    "tweeted_weekday": make_weekday(dt, timezone=timezone),
                    "tweeted_hour": dt.strftime("%H"),
                    "tweet_id": t.id,
                    "favorite_count": t.favorite_count,
                    "retweet_count": t.retweet_count,
                    "source": t.source,
                    "user_id": t.user.id,
                    "user_screen_name": t.user.screen_name,
                    "user_name": t.user.name,
                    "user_profile_image_url": t.user.profile_image_url_https,
                    "followers_count": t.user.followers_count,
                    "friends_count": t.user.friends_count,
                    "following": t.user.following,
                    "follower": False,  # フォロワーかどうかはsearchから取得できない（別でセットする手段を用意する）
                }
            )

            if limit and len(tweets) >= limit:
                limited = True
                break

        logger.info(f"{'{:,}'.format(len(tweets))} 件取得")
        if limited:
            break

        next_max_tweet_id = _tweets[-1].id - 1
        time.sleep(1)

    return tweets


def _make_search_from_query(timezone) -> str:
    """検索日付のFromに指定するクエリを生成する

    TwitterAPIの無料プランでは8日前のツイートも取得できるが、
    24時間分は取得できていないため、分析対象から除外する。

    :param timezone: timezoneオブジェクト
    :return 検索日付From形式の文字列
    """
    _dt = datetime.now(timezone) - timedelta(days=7)
    return _convert_search_period_query_format(_dt.date())


def _make_excluded_today_search_to_query(timezone) -> str:
    """当日除外用に検索日付のToに指定するクエリを生成する

    当日のツイートは24時間分は取得できていないため、
    ユーザから指定された場合のみ、分析対象から除外する。

    :param timezone: timezoneオブジェクト
    :return 検索日付To形式の文字列
    """
    _today = datetime.now(timezone).date()
    return _convert_search_period_query_format(_today)


def _convert_search_period_query_format(dt: Union[datetime, date]) -> str:
    """検索日付のFrom/Toに指定する形式の文字列を生成する

    :param dt: datetime or date
    :return 検索日付From形式の文字列
    """
    return dt.strftime("since:%Y-%m-%d_%H:%M:%S_JST")


def _convert_timezone(dt: datetime, timezone) -> datetime:
    """UTC時間を指定されたtimezoneに変更

    Twitter APIから取得した時間はtimestamp

    :param dt: datetime(UTC)
    :param timezone: timezoneオブジェクト
    :return timezone変換後のdatetime
    """
    utc_dt = datetime(
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        tzinfo=pytz.timezone("UTC"),
    )
    return utc_dt.astimezone(timezone)
