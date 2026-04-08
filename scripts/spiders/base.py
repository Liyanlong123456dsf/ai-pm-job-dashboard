"""爬虫基类：统一接口 + 反爬基础设施"""
import requests
import random
import time
import logging

logger = logging.getLogger('spider')

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0',
]


class BaseSpider:
    platform = 'base'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })

    def _sleep(self, lo=3, hi=8):
        t = random.uniform(lo, hi)
        time.sleep(t)

    def search(self, keyword: str, city_code: str) -> list:
        raise NotImplementedError

    def run(self, keywords: list, cities: dict) -> list:
        all_jobs = []
        for kw in keywords:
            for city_name, city_code in cities.items():
                try:
                    logger.info(f'[{self.platform}] {kw} @ {city_name}')
                    jobs = self.search(kw, city_code)
                    for j in jobs:
                        j['_city_name'] = city_name
                    all_jobs.extend(jobs)
                    self._sleep()
                except Exception as e:
                    logger.error(f'[{self.platform}] {kw}@{city_name} error: {e}')
                    self._sleep(5, 15)
        logger.info(f'[{self.platform}] total raw: {len(all_jobs)}')
        return all_jobs
