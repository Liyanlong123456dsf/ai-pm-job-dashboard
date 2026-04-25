"""BOSS直聘爬虫 - 通过搜索页面抓取 AI PM 岗位"""
import re
import json
import logging
from .base import BaseSpider

logger = logging.getLogger('spider.boss')


class BossSpider(BaseSpider):
    platform = 'boss'

    SEARCH_URL = 'https://www.zhipin.com/wapi/zpgeek/search/joblist.json'
    DETAIL_URL = 'https://www.zhipin.com/wapi/zpgeek/job/detail.json'

    def __init__(self, cookie: str = ''):
        super().__init__()
        self.session.headers.update({
            'Referer': 'https://www.zhipin.com/',
            'Origin': 'https://www.zhipin.com',
        })
        if cookie:
            self.session.headers['Cookie'] = cookie

    def search(self, keyword: str, city_code: str, fetch_detail: bool = True) -> list:
        results = []
        for page in range(1, 4):  # max 3 pages
            params = {
                'query': keyword,
                'city': city_code,
                'page': page,
                'pageSize': 30,
            }
            try:
                resp = self.session.get(self.SEARCH_URL, params=params, timeout=15)
                data = resp.json()

                if data.get('code') != 0:
                    logger.warning(f'BOSS API code={data.get("code")}, msg={data.get("message")}')
                    break

                job_list = data.get('zpData', {}).get('jobList', [])
                if not job_list:
                    break

                for item in job_list:
                    job = self._parse_item(item)
                    if job:
                        # 获取完整职位描述
                        if fetch_detail and job.get('_security_id'):
                            detail = self.get_detail(job['_security_id'])
                            if detail:
                                job['desc'] = detail
                            self._sleep(0.5, 1.5)
                        results.append(job)

                self._sleep(2, 5)

            except Exception as e:
                logger.error(f'BOSS search error page={page}: {e}')
                break

        return results

    def _parse_item(self, item: dict) -> dict:
        try:
            skills = item.get('skills', [])
            labels = item.get('jobLabels', '')
            return {
                'title': item.get('jobName') or '',
                'company': item.get('brandName') or '',
                'city': (item.get('cityName') or ''),
                'salary': item.get('salaryDesc') or '',
                'exp': item.get('jobExperience') or '',
                'edu': item.get('jobDegree') or '',
                'desc': ' '.join(skills) + (' ' + labels if labels else ''),
                'url': f"https://www.zhipin.com/job_detail/{item.get('encryptJobId', '')}.html" if item.get('encryptJobId') else '',
                '_security_id': item.get('securityId', ''),
                '_source': 'boss',
            }
        except Exception:
            return None

    def get_detail(self, security_id: str) -> str:
        """获取岗位详细描述（可选，会增加请求量）"""
        try:
            resp = self.session.get(self.DETAIL_URL,
                                   params={'securityId': security_id},
                                   timeout=15)
            data = resp.json()
            return data.get('zpData', {}).get('jobInfo', {}).get('postDescription', '')
        except Exception:
            return ''
