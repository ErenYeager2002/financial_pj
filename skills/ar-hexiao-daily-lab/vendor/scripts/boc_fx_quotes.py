"""Strict BOC spot buying quotes: 100 foreign currency units in CNY.

Publication timestamps are China local time. This module never uses cash buying,
spot selling, or BOC conversion prices as a substitute for spot buying prices.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

OFFICIAL_URL = 'https://www.boc.cn/sourcedb/whpj/'
HISTORY_SHEET = '中行历史牌价'
CURRENCY_NAMES = {
    'AED': '阿联酋迪拉姆', 'AUD': '澳大利亚元', 'BND': '文莱元',
    'BRL': '巴西雷亚尔', 'CAD': '加拿大元', 'CHF': '瑞士法郎',
    'CZK': '捷克克朗', 'DKK': '丹麦克朗', 'EUR': '欧元', 'GBP': '英镑',
    'HKD': '港币', 'HUF': '匈牙利福林', 'IDR': '印尼卢比',
    'ILS': '以色列谢克尔', 'INR': '印度卢比', 'JPY': '日元',
    'KHR': '柬埔寨瑞尔', 'KRW': '韩国元', 'KWD': '科威特第纳尔',
    'KZT': '哈萨克斯坦坚戈', 'MNT': '蒙古图格里克', 'MOP': '澳门元',
    'MUR': '毛里求斯卢比', 'MXN': '墨西哥比索', 'MYR': '林吉特',
    'NOK': '挪威克朗', 'NPR': '尼泊尔卢比', 'NZD': '新西兰元',
    'PHP': '菲律宾比索', 'PKR': '巴基斯坦卢比', 'PLN': '波兰兹罗提',
    'QAR': '卡塔尔里亚尔', 'RON': '罗马尼亚列伊', 'RSD': '塞尔维亚第纳尔',
    'RUB': '卢布', 'SAR': '沙特里亚尔', 'SEK': '瑞典克朗', 'SGD': '新加坡元',
    'THB': '泰国铢', 'TRY': '土耳其里拉', 'TWD': '新台币', 'USD': '美元',
    'VND': '越南盾', 'ZAR': '南非兰特', 'ZMW': '赞比亚克瓦查',
}
_CURRENCY_CODES = {name: code for code, name in CURRENCY_NAMES.items()}
_CURRENCY_CODES.update({name + code: code for code, name in CURRENCY_NAMES.items()})
_CURRENCY_CODES.update({'人民币CNY': 'CNY', '人民币元CNY': 'CNY'})
_CURRENCY_CODES.update({
    '澳元': 'AUD', '加元': 'CAD', '瑞郎': 'CHF', '港元': 'HKD',
    '韩元': 'KRW', '新西兰币': 'NZD', '纽元': 'NZD', '美金': 'USD',
    '人民币': 'CNY', '人民币元': 'CNY', 'RMB': 'CNY',
})


class BOCQuoteError(ValueError):
    """A quote cannot safely be parsed or selected."""


class BOCQuoteUnavailableError(BOCQuoteError):
    """No eligible quote exists in the supplied records; another source may help."""


class BOCCoverageError(BOCQuoteError):
    """The downloaded official pages do not prove complete quote coverage."""


def normalize_currency(currency: str) -> str:
    value = re.sub(r'\s+', '', str(currency or '')).upper()
    if value in CURRENCY_NAMES or value == 'CNY':
        return value
    if value in _CURRENCY_CODES:
        return _CURRENCY_CODES[value]
    raise BOCQuoteError(f'不支持的中行牌价币种：{currency!r}')


def _day(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.datetime):
        raise BOCQuoteError('核销日期必须为日期，不含时间')
    if isinstance(value, dt.date):
        return value
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(value)):
        raise BOCQuoteError(f'无效核销日期：{value!r}；须为 YYYY-MM-DD')
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise BOCQuoteError(f'无效核销日期：{value!r}') from exc


def _price(value) -> Decimal | None:
    text = '' if value is None else str(value).strip()
    if text in ('', '-', '--', '—'):
        return None
    if not re.fullmatch(r'\d+(?:\.\d+)?', text):
        raise BOCQuoteError(f'无效现汇买入价：{text!r}')
    result = Decimal(text)
    if result <= 0:
        raise BOCQuoteError('现汇买入价必须大于零')
    return result


def _published(value, date_value=None) -> dt.datetime:
    def check_local_time(value):
        if value.tzinfo is not None or value.microsecond:
            raise BOCQuoteError('发布时间须为中国本地时间且精确到秒')
        return value

    def full_timestamp(text):
        text = str(text).strip()
        if not re.fullmatch(r'\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{2}:\d{2}:\d{2}', text):
            raise BOCQuoteError(f'发布时间缺少完整日期或秒：{text!r}')
        try:
            return dt.datetime.fromisoformat(text.replace('/', '-').replace('.', '-'))
        except ValueError as exc:
            raise BOCQuoteError(f'无效发布时间：{text!r}') from exc

    def date_parts(value):
        if isinstance(value, dt.datetime):
            check_local_time(value)
            # Excel stores date-only cells as midnight datetime values.
            return value.date(), value.time() if value.time() != dt.time() else None
        if isinstance(value, dt.date):
            return value, None
        text = str(value).strip().replace('/', '-').replace('.', '-')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            try:
                return dt.date.fromisoformat(text), None
            except ValueError as exc:
                raise BOCQuoteError(f'无效发布日期：{value!r}') from exc
        combined = full_timestamp(text)
        return combined.date(), combined.time()

    if isinstance(value, dt.datetime):
        timestamp = check_local_time(value)
    elif isinstance(value, dt.time):
        if date_value is None:
            raise BOCQuoteError('发布时间缺少完整日期')
        time_value = check_local_time(value)
        date_part, embedded_time = date_parts(date_value)
        timestamp = dt.datetime.combine(date_part, time_value)
    elif date_value is not None and re.fullmatch(r'\d{2}:\d{2}:\d{2}', str(value).strip()):
        try:
            time_value = dt.time.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise BOCQuoteError(f'无效发布时间：{value!r}') from exc
        date_part, embedded_time = date_parts(date_value)
        timestamp = dt.datetime.combine(date_part, time_value)
    else:
        timestamp = full_timestamp(value)
    if date_value is not None:
        date_part, embedded_time = date_parts(date_value)
        if timestamp.date() != date_part or (embedded_time is not None and timestamp.time() != embedded_time):
            raise BOCQuoteError('发布日期与发布时间不一致')
    return timestamp


@dataclass(frozen=True)
class BOCQuote:
    currency: str
    currency_name: str
    buying_price_per_100: Decimal | None
    published_at: dt.datetime
    source_kind: str
    source_reference: str
    source_sha256: str
    source_row: int

    @property
    def price_per_100(self) -> Decimal | None:
        return self.buying_price_per_100

    @property
    def rate_per_unit(self) -> Decimal:
        if self.buying_price_per_100 is None:
            raise BOCQuoteError(f'{self.currency} {self.published_at.isoformat()} 缺少现汇买入价')
        return self.buying_price_per_100 / Decimal('100')

    def to_snapshot(self, reconciliation_date: str | dt.date) -> dict:
        day = _day(reconciliation_date)
        if self.published_at.date() > day:
            raise BOCQuoteError('不能将核销日期之后的牌价固定为快照')
        return {
            'schema': 'boc_spot_buying_v1',
            'currency': self.currency,
            'currency_name': self.currency_name,
            'rate_type': '现汇买入价',
            'quoted_unit': 100,
            'buying_price_per_100': str(self.buying_price_per_100),
            'rate_cny_per_unit': str(self.rate_per_unit),
            'published_at': self.published_at.isoformat(),
            'timezone': 'Asia/Shanghai',
            'reconciliation_date': day.isoformat(),
            'selection': 'same_date_latest' if self.published_at.date() == day else 'closest_earlier',
            'source': {
                'name': '中国银行', 'kind': self.source_kind,
                'reference': self.source_reference, 'sha256': self.source_sha256,
                'row': self.source_row,
            },
        }


class _QuoteTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.active = False
        self.seen = False
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table' and dict(attrs).get('id') == 'priceTable':
            if self.seen:
                raise BOCQuoteError('官方牌价页含重复 priceTable')
            self.active = self.seen = True
        elif self.active and tag == 'table':
            raise BOCQuoteError('官方牌价表出现嵌套表格')
        elif self.active and tag == 'tr':
            if self.row is not None:
                raise BOCQuoteError('官方牌价行未正确闭合')
            self.row = []
        elif self.active and tag in ('td', 'th'):
            if self.row is None or self.cell is not None:
                raise BOCQuoteError('官方牌价格式错误')
            self.cell = []
        elif self.cell is not None and tag == 'br':
            self.cell.append(' ')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag in ('td', 'th'):
            if self.cell is None:
                raise BOCQuoteError('官方牌价格式错误')
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr':
            if self.row is None or self.cell is not None:
                raise BOCQuoteError('官方牌价行未正确闭合')
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            if self.row is not None or self.cell is not None:
                raise BOCQuoteError('官方牌价表未正确闭合')
            self.active = False


def _columns(header):
    if len(header) != len(set(header)):
        raise BOCQuoteError('牌价表包含重复列名')
    required = ('货币名称', '现汇买入价', '发布时间')
    if any(name not in header for name in required):
        raise BOCQuoteError('牌价表必须包含货币名称、现汇买入价、发布时间')
    return {name: header.index(name) for name in required + ('发布日期',) if name in header}


def _row_quote(row, columns, *, source_kind, source_reference, source_sha256, source_row):
    code = normalize_currency(row[columns['货币名称']])
    if code == 'CNY':
        raise BOCQuoteError('人民币不是中行外币牌价，不得导入为外币汇率')
    published = _published(row[columns['发布时间']], row[columns['发布日期']] if '发布日期' in columns else None)
    return BOCQuote(code, CURRENCY_NAMES[code], _price(row[columns['现汇买入价']]), published,
                    source_kind, source_reference, source_sha256, source_row)


def parse_boc_html(html: str, source_url: str = OFFICIAL_URL) -> list[BOCQuote]:
    """Parse all official table rows, preserving missing spot buying prices."""
    if not re.search(r'单位为\s*100\s*外币', html):
        raise BOCQuoteError('官方页面未确认每100外币报价单位')
    parser = _QuoteTableParser()
    parser.feed(html)
    parser.close()
    if parser.active or not parser.seen or len(parser.rows) < 2:
        raise BOCQuoteError('官方页面缺少完整的中行牌价表；可能为验证码或错误页面')
    header = parser.rows[0]
    columns = _columns(header)
    digest = hashlib.sha256(html.encode('utf-8')).hexdigest()
    result = []
    for row_no, row in enumerate(parser.rows[1:], 2):
        if len(row) != len(header):
            raise BOCQuoteError(f'官方牌价第{row_no}行列数不一致')
        result.append(_row_quote(row, columns, source_kind='official_page',
                                source_reference=source_url, source_sha256=digest, source_row=row_no))
    return result


def select_quote(quotes: Iterable[BOCQuote], currency: str, reconciliation_date: str | dt.date) -> BOCQuote:
    """Latest timestamp on the date; if absent, the closest earlier timestamp."""
    code, day = normalize_currency(currency), _day(reconciliation_date)
    if code == 'CNY':
        raise BOCQuoteError('人民币不需要中行外币牌价')
    candidates = [quote for quote in quotes if quote.currency == code and quote.published_at.date() <= day]
    if not candidates:
        raise BOCQuoteUnavailableError(f'{code} 在{day.isoformat()}及之前没有中行现汇买入牌价；请导入中行历史牌价')
    latest = max(quote.published_at for quote in candidates)
    selected = [quote for quote in candidates if quote.published_at == latest]
    if len({quote.buying_price_per_100 for quote in selected}) != 1:
        raise BOCQuoteError(f'{code} {latest.isoformat()} 存在冲突的现汇买入价')
    chosen = selected[0]
    chosen.rate_per_unit  # A blank latest buying quote must never fall back to cash or an older quote.
    return chosen



def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_workbook_quotes(paths: Iterable[str | Path]) -> list[BOCQuote]:
    """Read 中行历史牌价 from the selected annual workbooks without modifying them.

    An absent/empty sheet supplies no quotes. A present malformed quote table is
    an error, so it cannot quietly switch the task to another rate source.
    Imported buying prices always quote CNY per 100 foreign currency units.
    """
    from openpyxl import load_workbook

    quotes = []
    for value in paths:
        path = Path(value)
        try:
            digest = _file_sha256(path)
            book = load_workbook(path, read_only=True, data_only=False)
        except Exception as exc:
            raise BOCQuoteError(f'不能读取中行历史牌价来源工作簿：{path.name}') from exc
        try:
            if HISTORY_SHEET not in book.sheetnames:
                continue
            sheet = book[HISTORY_SHEET]
            if sheet.max_row and sheet.max_row > 250000:
                raise BOCQuoteError('中行历史牌价工作表超过250000行读取上限')
            columns, header_width = None, None
            for row_no, cells in enumerate(sheet.iter_rows(), 1):
                row = [cell.value for cell in cells]
                while row and row[-1] in (None, ''):
                    row.pop()
                if not row:
                    continue
                if columns is None:
                    header = ['' if cell is None else str(cell).strip() for cell in row]
                    columns, header_width = _columns(header), len(header)
                    continue
                if len(row) > header_width:
                    raise BOCQuoteError(f'{path.name} 中行历史牌价第{row_no}行存在无列名数据')
                row.extend([None] * (header_width - len(row)))
                if any(isinstance(row[index], str) and row[index].startswith('=') for index in columns.values()):
                    raise BOCQuoteError(f'{path.name} 中行历史牌价第{row_no}行须为原始值，不能使用公式')
                publication_cell = cells[columns['发布时间']]
                publication_value = publication_cell.value
                format_code = re.sub(r'"[^"]*"|\\.', '', publication_cell.number_format or '').lower()
                if (isinstance(publication_value, dt.datetime) and publication_value.time() == dt.time()
                        and not re.search(r'[hs]', format_code)):
                    raise BOCQuoteError(f'{path.name} 中行历史牌价第{row_no}行缺少发布时间，日期不能推定为零点报价')
                try:
                    quote = _row_quote(row, columns, source_kind='imported_workbook',
                                       source_reference=f'{path.name}#{HISTORY_SHEET}',
                                       source_sha256=digest, source_row=row_no)
                except BOCQuoteError as exc:
                    raise BOCQuoteError(f'{path.name} 中行历史牌价第{row_no}行：{exc}') from exc
                quotes.append(quote)
        finally:
            book.close()
        if _file_sha256(path) != digest:
            raise BOCQuoteError(f'{path.name} 在读取中行历史牌价期间被修改')
    return quotes



def _pagination(html: str) -> tuple[int, int]:
    calls = re.findall(r'createPageHTML\(\s*(\d+)\s*,\s*(\d+)\s*,\s*[\'"]index[\'"]\s*,\s*[\'"]html[\'"]\s*\)', html)
    if len(calls) != 1:
        raise BOCCoverageError('官方牌价页未提供唯一完整分页信息')
    count, index = map(int, calls[0])
    if count < 1 or not 0 <= index < count:
        raise BOCCoverageError('官方牌价页分页信息无效')
    return count, index



@dataclass(frozen=True)
class _OfficialQuoteBook:
    quotes: tuple[BOCQuote, ...]
    page_currencies: tuple[frozenset[str], ...]


# One process shares a fully parsed book across currencies and reconciliation dates.
# Expiration bounds freshness if the caller process is reused for another task.
_OFFICIAL_BOOK_CACHE: dict[tuple, tuple[float, _OfficialQuoteBook]] = {}


def _fetch_official_book(timeout, max_pages, total_timeout, max_response_bytes) -> _OfficialQuoteBook:
    deadline = time.monotonic() + total_timeout

    def download(url):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BOCCoverageError('中行官方牌价抓取达到总超时上限；请导入中行历史牌价')
        request = urllib.request.Request(url, headers={'User-Agent': 'FinancialReconciliation/1.0', 'Accept': 'text/html'})
        try:
            with urllib.request.urlopen(request, timeout=min(timeout, remaining)) as response:
                if response.geturl() != url:
                    raise BOCCoverageError('中行官方牌价请求被重定向，未使用非指定页面')
                if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
                    raise BOCCoverageError('中行官方牌价返回非HTML内容')
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise BOCCoverageError('中行官方牌价响应超过大小上限，不能使用截断数据')
                charset = response.headers.get_content_charset() or 'utf-8'
                html = body.decode(charset, errors='strict')
        except BOCCoverageError:
            raise
        except Exception as exc:
            # Do not expose server response bodies, proxy settings, or credentials.
            raise BOCCoverageError('无法完整读取中行官方牌价页面；请导入中行历史牌价') from exc
        if time.monotonic() > deadline:
            raise BOCCoverageError('中行官方牌价抓取达到总超时上限；请导入中行历史牌价')
        return html

    first = download(OFFICIAL_URL)
    page_count, page_index = _pagination(first)
    if page_index != 0 or page_count > max_pages:
        raise BOCCoverageError('中行官方牌价分页超过读取上限或首页页号异常，不能使用不完整数据')
    quotes, page_currencies = [], []
    for index in range(page_count):
        url = OFFICIAL_URL if index == 0 else f'{OFFICIAL_URL}index_{index}.html'
        html = first if index == 0 else download(url)
        if _pagination(html) != (page_count, index):
            raise BOCCoverageError('中行官方牌价分页在读取期间改变，未固定不完整牌价')
        try:
            page_quotes = parse_boc_html(html, source_url=url)
        except BOCQuoteError as exc:
            raise BOCCoverageError(f'中行官方牌价第{index + 1}页无法完整解析；请导入中行历史牌价') from exc
        currencies = frozenset(quote.currency for quote in page_quotes)
        if len(currencies) != len(page_quotes):
            raise BOCCoverageError(f'中行官方牌价第{index + 1}页币种重复，不能证明完整分页')
        page_currencies.append(currencies)
        quotes.extend(page_quotes)
    # Page counts can remain constant while new publications rotate every page.
    # Read back the first source within the same deadline before fixing any book.
    readback = download(OFFICIAL_URL)
    if (hashlib.sha256(first.encode('utf-8')).digest()
            != hashlib.sha256(readback.encode('utf-8')).digest()):
        raise BOCCoverageError('中行官方牌价首页在分页读取期间发生变化，未固定不完整牌价')
    return _OfficialQuoteBook(tuple(quotes), tuple(page_currencies))


def fetch_official_quotes(currency: str, reconciliation_date: str | dt.date, *,
                          timeout: float = 5.0, max_pages: int = 10,
                          total_timeout: float = 45.0,
                          max_response_bytes: int = 1024 * 1024,
                          use_cache: bool = True) -> BOCQuote:
    """Fetch every declared current official page before choosing a quote.

    No CAPTCHA/search endpoints are accessed. Failure, truncation, missing target
    currency, or changing page counts rejects coverage instead of using an older
    page. The first page is read back before accepting a book; any source change
    rejects it without retry. Dates outside this current window require an imported table.
    Fully validated books are shared in-process for at most 300 seconds. Disable
    use_cache for callers explicitly requiring a fresh network read.
    """
    code, day = normalize_currency(currency), _day(reconciliation_date)
    if code == 'CNY':
        raise BOCQuoteError('人民币不需要中行外币牌价')
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not 0 < timeout <= 30
            or not isinstance(total_timeout, (int, float)) or isinstance(total_timeout, bool)
            or not 0 < total_timeout <= 120
            or not isinstance(max_pages, int) or isinstance(max_pages, bool)
            or not 1 <= max_pages <= 20
            or not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool)
            or not 1 <= max_response_bytes <= 4 * 1024 * 1024
            or not isinstance(use_cache, bool)):
        raise BOCQuoteError('官方牌价抓取超时、页数或响应大小上限无效')
    key = (timeout, max_pages, total_timeout, max_response_bytes)
    cached = _OFFICIAL_BOOK_CACHE.get(key) if use_cache else None
    if cached is not None and time.monotonic() < cached[0]:
        book = cached[1]
    else:
        book = _fetch_official_book(timeout, max_pages, total_timeout, max_response_bytes)
        if use_cache:
            if len(_OFFICIAL_BOOK_CACHE) >= 8:
                _OFFICIAL_BOOK_CACHE.pop(next(iter(_OFFICIAL_BOOK_CACHE)))
            _OFFICIAL_BOOK_CACHE[key] = (time.monotonic() + 300, book)
    for index, currencies in enumerate(book.page_currencies):
        if code not in currencies:
            raise BOCCoverageError(f'中行官方牌价第{index + 1}页缺少唯一的{code}记录，不能退用较早页面')
    return select_quote(book.quotes, code, day)
