#!/usr/bin/env python3
"""
同步 knowledge_base.md 到飞书云文档

每次爬取完自动调用，将最新知识库内容写入飞书文档。
扣子(Coze) 通过飞书知识库连接器读取该文档，实现数据自动更新。

配置：
  在项目根目录 .env 文件或环境变量中设置：
    FEISHU_APP_ID=cli_xxxxxxxxxx
    FEISHU_APP_SECRET=xxxxxxxxxx

  首次运行会自动创建飞书文档，document_id 保存在 logs/feishu_doc.json
  后续运行会更新同一文档内容。
"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import json
import time
import hashlib
import logging
import requests
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
DOC_STATE_FILE = LOG_DIR / 'feishu_doc.json'
KB_FILE = BASE_DIR / 'knowledge_base.md'

logger = logging.getLogger('sync_feishu')
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [feishu] %(levelname)s: %(message)s',
    )

# ============ 飞书 API 常量 ============
FEISHU_HOST = 'https://open.feishu.cn'
TENANT_TOKEN_URL = f'{FEISHU_HOST}/open-apis/auth/v3/tenant_access_token/internal'
CREATE_DOC_URL = f'{FEISHU_HOST}/open-apis/docx/v1/documents'
# 文档块操作
DOC_BLOCKS_URL = lambda doc_id: f'{FEISHU_HOST}/open-apis/docx/v1/documents/{doc_id}/blocks'
DOC_BLOCK_CHILDREN_URL = lambda doc_id, block_id: f'{FEISHU_HOST}/open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}/children'
DOC_BATCH_DELETE_URL = lambda doc_id, block_id: f'{FEISHU_HOST}/open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}/children/batch_delete'

# 飞书文档每次创建子块数量限制
BATCH_SIZE = 50

MAX_REQUEST_RETRIES = 5
RETRY_BACKOFF_SEC = 2


def _truncate_text(value, limit=200):
    text = str(value or '')
    return text if len(text) <= limit else text[:limit]


def _is_retryable_feishu_error(data):
    if not isinstance(data, dict):
        return False
    if data.get('code') == 99991400:
        return True
    payload = json.dumps(data, ensure_ascii=False).lower()
    return any(token in payload for token in ['rate', 'limit', 'frequency', 'internal', 'busy', 'timeout', 'tempor'])


def _request_with_retry(method, url, *, timeout, action='', **kwargs):
    action = action or f'{method.upper()} {url}'
    last_error = None
    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f'HTTP {resp.status_code}: {_truncate_text(resp.text)}', response=resp)

            data = None
            try:
                data = resp.json()
            except Exception:
                data = None

            if isinstance(data, dict) and data.get('code') not in (None, 0):
                if attempt < MAX_REQUEST_RETRIES and _is_retryable_feishu_error(data):
                    wait_sec = min(30, RETRY_BACKOFF_SEC * attempt)
                    logger.warning(f'{action} 第{attempt}次命中可重试错误，{wait_sec} 秒后重试: {_truncate_text(data)}')
                    time.sleep(wait_sec)
                    continue
                raise ValueError(f'{action} 失败: {data}')

            resp.raise_for_status()
            return resp
        except (requests.RequestException, ValueError) as e:
            last_error = e
            if attempt >= MAX_REQUEST_RETRIES:
                break
            wait_sec = min(30, RETRY_BACKOFF_SEC * attempt)
            logger.warning(f'{action} 第{attempt}次失败，{wait_sec} 秒后重试: {_truncate_text(e)}')
            time.sleep(wait_sec)
    raise last_error


def get_credentials():
    """获取飞书凭证（优先环境变量，其次 .env 文件）"""
    app_id = os.environ.get('FEISHU_APP_ID', '')
    app_secret = os.environ.get('FEISHU_APP_SECRET', '')

    if not app_id or not app_secret:
        env_file = BASE_DIR / '.env'
        if env_file.exists():
            for line in env_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip()
                if k == 'FEISHU_APP_ID':
                    app_id = v
                elif k == 'FEISHU_APP_SECRET':
                    app_secret = v

    if not app_id or not app_secret:
        raise ValueError('飞书凭证未配置，请在 .env 中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET')
    return app_id, app_secret


def get_tenant_token(app_id, app_secret):
    """获取 tenant_access_token"""
    resp = _request_with_retry('post', TENANT_TOKEN_URL, action='获取 tenant_access_token', json={
        'app_id': app_id,
        'app_secret': app_secret,
    }, timeout=10)
    data = resp.json()
    token = data['tenant_access_token']
    logger.info(f'✅ 获取 tenant_access_token 成功（有效期 {data.get("expire", 0)}s）')
    return token


def create_document(token, title):
    """创建新的飞书文档，返回 document_id"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    resp = _request_with_retry('post', CREATE_DOC_URL, action='创建飞书文档', headers=headers, json={
        'title': title,
    }, timeout=15)
    data = resp.json()
    doc = data['data']['document']
    doc_id = doc['document_id']
    logger.info(f'✅ 飞书文档已创建: {doc_id}')
    # 自动开放文档权限：任何人可编辑
    try:
        perm_resp = _request_with_retry(
            'patch',
            f'{FEISHU_HOST}/open-apis/drive/v2/permissions/{doc_id}/public?type=docx',
            action='设置文档公开权限',
            headers=headers,
            json={
                'external_access_entity': 'open',
                'link_share_entity': 'anyone_editable',
                'share_entity': 'anyone',
            },
            timeout=10,
        )
        if perm_resp.json().get('code') == 0:
            logger.info('✅ 文档已设置为任何人可编辑')
    except Exception as e:
        logger.warning(f'⚠️ 权限设置异常: {e}')
    return doc_id


def get_document_blocks(token, doc_id):
    """获取文档的所有顶层块"""
    headers = {'Authorization': f'Bearer {token}'}
    blocks = []
    page_token = None
    while True:
        params = {'page_size': 500}
        if page_token:
            params['page_token'] = page_token
        resp = _request_with_retry('get', DOC_BLOCKS_URL(doc_id), action='获取文档顶层块', headers=headers, params=params, timeout=15)
        data = resp.json()
        items = data.get('data', {}).get('items', [])
        blocks.extend(items)
        page_token = data.get('data', {}).get('page_token')
        if not data.get('data', {}).get('has_more'):
            break
    return blocks


def get_block_children(token, doc_id, block_id):
    """获取指定块的子块"""
    headers = {'Authorization': f'Bearer {token}'}
    children = []
    page_token = None
    while True:
        params = {'page_size': 500}
        if page_token:
            params['page_token'] = page_token
        resp = _request_with_retry('get', DOC_BLOCK_CHILDREN_URL(doc_id, block_id), action='获取文档子块', headers=headers, params=params, timeout=15)
        data = resp.json()
        items = data.get('data', {}).get('items', [])
        children.extend(items)
        page_token = data.get('data', {}).get('page_token')
        if not data.get('data', {}).get('has_more'):
            break
    return children


def clear_document(token, doc_id):
    """清空文档所有子块（高效版：先统计总数，然后循环从头删50个，无需每次重查）"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    # 先获取总子块数
    children = get_block_children(token, doc_id, doc_id)
    remaining = len(children)
    if remaining == 0:
        return 0
    total_deleted = 0
    logger.info(f'  共 {remaining} 个子块需要删除...')
    while remaining > 0:
        # 每次删除前 50 个（删除后后面的块自动前移）
        count = min(remaining, BATCH_SIZE)
        resp = _request_with_retry(
            'delete',
            DOC_BATCH_DELETE_URL(doc_id, doc_id),
            action='删除文档块',
            headers=headers,
            json={'start_index': 0, 'end_index': count},
            timeout=15,
        )
        data = resp.json()
        if data.get('code') == 0:
            total_deleted += count
            remaining -= count
            if total_deleted % 500 == 0 or remaining == 0:
                logger.info(f'  已删除 {total_deleted} 个块，剩余 {remaining}...')
        else:
            logger.warning(f'删除失败: {resp.status_code} {resp.text[:200]}')
            break
        time.sleep(0.15)
    return total_deleted


def md_to_blocks(md_content):
    """将 Markdown 文本转为飞书文档块列表（合并连续文本行减少块数）
    
    飞书 block_type:
      2=文本, 3=标题1, 4=标题2, 5=标题3, 6=标题4, 7=标题5, 8=标题6,
      15=引用, 22=分割线
    """
    blocks = []
    # 飞书标题 block_type: # -> 3, ## -> 4, ### -> 5, ...
    heading_type_map = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8}
    heading_key_map = {3: 'heading1', 4: 'heading2', 5: 'heading3',
                       6: 'heading4', 7: 'heading5', 8: 'heading6'}

    # 按 ===== 分隔符拆分为岗位段落
    sections = md_content.split('\n=====\n')

    for sec_idx, section in enumerate(sections):
        lines = section.strip().split('\n')
        if not lines:
            continue

        # 第一个段落（标题+概要信息）保留结构
        if sec_idx == 0:
            for line in lines:
                line_s = line.strip()
                if not line_s:
                    continue
                if line_s.startswith('#'):
                    level = 0
                    for ch in line_s:
                        if ch == '#':
                            level += 1
                        else:
                            break
                    level = min(level, 6)
                    text = line_s[level:].strip()
                    if text:
                        bt = heading_type_map.get(level, 8)
                        key = heading_key_map[bt]
                        blocks.append({
                            'block_type': bt,
                            key: {
                                'elements': [{'text_run': {'content': text[:4500], 'text_element_style': {}}}],
                                'style': {},
                            }
                        })
                elif line_s.startswith('>'):
                    text = line_s[1:].strip()
                    if text:
                        blocks.append({
                            'block_type': 2,
                            'text': {
                                'elements': [{'text_run': {'content': text[:4500], 'text_element_style': {'italic': True}}}],
                                'style': {},
                            }
                        })
                else:
                    blocks.append({
                        'block_type': 2,
                        'text': {
                            'elements': [{'text_run': {'content': line_s[:4500], 'text_element_style': {}}}],
                            'style': {},
                        }
                    })
            continue

        # 后续岗位段落：===== 分隔符 + 标题加粗 + 正文，合并为单个文本块
        # 保留 ===== 分隔符供扣子 RAG 按此切割 chunk
        heading_text = ''
        body_lines = []
        for line in lines:
            line_s = line.strip()
            if not line_s:
                continue
            if line_s.startswith('#') and not heading_text:
                level = 0
                for ch in line_s:
                    if ch == '#':
                        level += 1
                    else:
                        break
                heading_text = line_s[level:].strip()
            else:
                body_lines.append(line_s)

        # 将分隔符+标题+正文合为一个文本块
        elements = []
        # ===== 作为 chunk 分隔标记（扣子 RAG 按此切割）
        elements.append({'text_run': {'content': '=====\n', 'text_element_style': {}}})
        if heading_text:
            elements.append({'text_run': {'content': heading_text[:4500] + '\n', 'text_element_style': {'bold': True}}})
        if body_lines:
            body = '\n'.join(body_lines)
            for i in range(0, len(body), 4000):
                elements.append({'text_run': {'content': body[i:i+4000], 'text_element_style': {}}})

        if elements:
            blocks.append({
                'block_type': 2,
                'text': {'elements': elements, 'style': {}},
            })

    return blocks


def create_block_children(token, doc_id, block_id, blocks):
    """批量在指定块下创建子块"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    total = len(blocks)
    created = 0

    for i in range(0, total, BATCH_SIZE):
        batch = blocks[i:i + BATCH_SIZE]
        body = {
            'children': batch,
            'index': -1,  # 追加到末尾
        }
        resp = _request_with_retry(
            'post',
            DOC_BLOCK_CHILDREN_URL(doc_id, block_id),
            action=f'写入文档块[{i + len(batch)}/{total}]',
            headers=headers,
            json=body,
            timeout=30,
        )
        data = resp.json()
        if data.get('code') == 0:
            created += len(batch)
        else:
            logger.error(f'创建块失败: {data}')
            break

        if created % 200 == 0 or created == total:
            logger.info(f'  进度: {created}/{total} 块')
        time.sleep(0.15)  # 控制频率（飞书限频 3/s，网络延迟已占 ~0.2s）

    return created


def load_doc_state():
    """加载已保存的文档状态"""
    if DOC_STATE_FILE.exists():
        try:
            return json.loads(DOC_STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def save_doc_state(state):
    """保存文档状态"""
    DOC_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    logger.info('=' * 50)
    logger.info('📄 开始同步 knowledge_base.md → 飞书云文档')
    logger.info('=' * 50)

    # 1. 读取知识库文件
    if not KB_FILE.exists():
        logger.error(f'❌ knowledge_base.md 不存在: {KB_FILE}')
        return False

    md_content = KB_FILE.read_text(encoding='utf-8')
    content_md5 = hashlib.md5(md_content.encode('utf-8')).hexdigest()
    logger.info(f'📄 知识库文件: {len(md_content)} 字符, {md_content.count(chr(10))} 行, MD5={content_md5[:8]}')

    # 2. 获取飞书凭证和 token
    try:
        app_id, app_secret = get_credentials()
        token = get_tenant_token(app_id, app_secret)
    except Exception as e:
        logger.error(f'❌ 飞书认证失败: {e}')
        return False

    # 3. 获取或创建文档
    state = load_doc_state()
    doc_id = state.get('document_id')

    if not doc_id:
        logger.info('📝 首次运行，创建新飞书文档...')
        try:
            doc_id = create_document(token, 'AI产品经理岗位知识库')
            state['document_id'] = doc_id
            state['created_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            save_doc_state(state)
            logger.info(f'✅ 文档已创建: {doc_id}')
            logger.info(f'   飞书文档链接: https://bytedance.feishu.cn/docx/{doc_id}')
        except Exception as e:
            logger.error(f'❌ 创建文档失败: {e}')
            return False
    else:
        logger.info(f'📝 使用已有文档: {doc_id}')
        # MD5 校验：内容未变则跳过同步
        if state.get('content_md5') == content_md5:
            logger.info('⏭️  内容无变化，跳过同步')
            return True

    # 4. 清空文档现有内容
    logger.info('🗑️  清空文档现有内容...')
    try:
        deleted = clear_document(token, doc_id)
        logger.info(f'✅ 文档内容已清空（删除 {deleted} 个块）')
    except Exception as e:
        logger.warning(f'⚠️ 清空文档失败（可能是新文档）: {e}')

    # 5. 将 Markdown 转换为飞书块
    logger.info('🔄 转换 Markdown → 飞书文档块...')
    blocks = md_to_blocks(md_content)
    logger.info(f'  生成 {len(blocks)} 个文档块')

    # 6. 写入文档
    logger.info('📝 写入飞书文档...')
    try:
        created = create_block_children(token, doc_id, doc_id, blocks)
        logger.info(f'✅ 已写入 {created}/{len(blocks)} 个块')
    except Exception as e:
        logger.error(f'❌ 写入文档失败: {e}')
        return False

    # 7. 更新状态
    state['last_sync'] = time.strftime('%Y-%m-%d %H:%M:%S')
    state['blocks_count'] = len(blocks)
    state['content_size'] = len(md_content)
    state['content_md5'] = content_md5
    save_doc_state(state)

    logger.info('=' * 50)
    logger.info(f'✅ 飞书文档同步完成')
    logger.info(f'   文档ID: {doc_id}')
    logger.info(f'   链接: https://bytedance.feishu.cn/docx/{doc_id}')
    logger.info(f'   块数: {len(blocks)} | 内容: {len(md_content)} 字符')
    logger.info('=' * 50)
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
