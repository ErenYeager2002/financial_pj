import unittest
import datetime as dt
import tempfile
import io
import json
from email.message import Message
from unittest.mock import patch
from pathlib import Path
from openpyxl import Workbook
from decimal import Decimal

from boc_fx_quotes import parse_boc_html, select_quote, load_workbook_quotes, fetch_official_quotes, BOCCoverageError, BOCQuoteError, BOCQuoteUnavailableError, normalize_currency


def quote_page(rows, page_count=1, page_index=0):
    header = '<tr><th>货币名称</th><th>现汇买入价</th><th>现钞买入价</th><th>现汇卖出价</th><th>中行折算价</th><th>发布日期</th><th>发布时间</th></tr>'
    body = ''.join('<tr>' + ''.join('<td>' + str(cell) + '</td>' for cell in row) + '</tr>' for row in rows)
    return '<table id="priceTable">' + header + body + '</table>本汇率表单位为100外币换算人民币<script>createPageHTML(%s, %s, "index", "html");</script>' % (page_count, page_index)


class BOCQuoteTests(unittest.TestCase):
    def test_latest_date_buying_quote_is_converted_from_100_units(self):
        quotes = parse_boc_html(quote_page([
            ['美元', '703.25', '690', '710', '707', '2026/08/05 09:00:00', '09:00:00'],
            ['美元', '705.12', '692', '712', '709', '2026/08/05 16:30:00', '16:30:00'],
            ['美元', '706.88', '694', '714', '711', '2026/08/06 10:00:00', '10:00:00'],
        ]))
        chosen = select_quote(quotes, 'USD', '2026-08-05')
        self.assertEqual(chosen.buying_price_per_100, Decimal('705.12'))
        self.assertEqual(chosen.rate_per_unit, Decimal('7.0512'))
        self.assertEqual(chosen.published_at.isoformat(), '2026-08-05T16:30:00')

    def test_selected_annual_workbooks_supply_attributed_historical_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'annual2025.xlsx', Path(directory) / 'annual2026.xlsx'
            book = Workbook()
            sheet = book.create_sheet('中行历史牌价')
            sheet.append(['货币名称', '现汇买入价', '发布时间'])
            sheet.append(['USD', 708.25, dt.datetime(2025, 12, 31, 20, 0)])
            book.save(first)
            book.close()
            book = Workbook()
            sheet = book.create_sheet('中行历史牌价')
            sheet.append(['货币名称', '现汇买入价', '发布日期', '发布时间'])
            sheet.append(['美元', 706.25, dt.date(2026, 1, 2), dt.time(10, 0)])
            sheet.append(['美元', 707.18, '2026/01/02', '18:00:00'])
            book.save(second)
            book.close()
            quotes = load_workbook_quotes([first, second])
            chosen = select_quote(quotes, '美元', '2026-01-03')
            self.assertEqual(chosen.rate_per_unit, Decimal('7.0718'))
            snapshot = chosen.to_snapshot('2026-01-03')
            self.assertEqual(snapshot['selection'], 'closest_earlier')
            self.assertEqual(snapshot['source']['kind'], 'imported_workbook')
            self.assertEqual(snapshot['source']['reference'], 'annual2026.xlsx#中行历史牌价')
            self.assertEqual(snapshot['source']['row'], 3)
            self.assertRegex(snapshot['source']['sha256'], r'^[0-9a-f]{64}$')
            self.assertEqual(select_quote(quotes, 'USD', '2026-01-01').rate_per_unit, Decimal('7.0825'))

    def test_official_fetch_never_skips_a_failed_newer_page(self):
        pages = {
            'https://www.boc.cn/sourcedb/whpj/': quote_page([
                ['美元', '708.25', '', '', '', '2026/08/05 20:00:00', '20:00:00'],
            ], page_count=3, page_index=0),
            'https://www.boc.cn/sourcedb/whpj/index_1.html': quote_page([
                ['美元', '706.25', '', '', '', '2026/08/05 12:00:00', '12:00:00'],
            ], page_count=3, page_index=1),
            'https://www.boc.cn/sourcedb/whpj/index_2.html': quote_page([
                ['美元', '704.25', '', '', '', '2026/08/04 20:00:00', '20:00:00'],
            ], page_count=3, page_index=2),
        }
        calls = []
        def opened(request, timeout):
            url = request.full_url
            calls.append(url)
            return HTMLResponse(pages[url], url)
        with patch('boc_fx_quotes.urllib.request.urlopen', side_effect=opened):
            chosen = fetch_official_quotes('USD', '2026-08-05', use_cache=False)
            self.assertEqual(chosen.rate_per_unit, Decimal('7.0825'))
            self.assertEqual(calls, list(pages) + ['https://www.boc.cn/sourcedb/whpj/'])
        def failure(request, timeout):
            if request.full_url.endswith('index_1.html'):
                raise TimeoutError('no response')
            return opened(request, timeout)
        with patch('boc_fx_quotes.urllib.request.urlopen', side_effect=failure):
            with self.assertRaises(BOCCoverageError):
                fetch_official_quotes('USD', '2026-08-04', use_cache=False)

    def test_no_date_quote_uses_latest_timestamp_on_closest_earlier_date(self):
        quotes = parse_boc_html(quote_page([
            ['欧元', '780', '770', '790', '785', '2026/08/01 10:00:00', '10:00:00'],
            ['欧元', '782.66', '772', '792', '787', '2026/08/01 21:59:59', '21:59:59'],
            ['欧元', '795', '785', '805', '800', '2026/08/04 10:00:00', '10:00:00'],
            ['港币', '90', '89', '91', '90', '2026/08/03 20:00:00', '20:00:00'],
        ]))
        self.assertEqual(select_quote(quotes, 'EUR', '2026-08-03').rate_per_unit, Decimal('7.8266'))
        self.assertEqual(select_quote(quotes, 'HKD', '2026-08-03').rate_per_unit, Decimal('0.9'))
        with self.assertRaises(BOCQuoteUnavailableError):
            select_quote(quotes, 'EUR', '2026-07-31')

    def test_latest_blank_buying_quote_does_not_use_cash_or_older_buying_quote(self):
        quotes = parse_boc_html(quote_page([
            ['美元', '705', '700', '715', '710', '2026/08/05 10:00:00', '10:00:00'],
            ['美元', '', '702', '717', '712', '2026/08/05 20:00:00', '20:00:00'],
        ]))
        with self.assertRaisesRegex(BOCQuoteError, '缺少现汇买入价'):
            select_quote(quotes, 'USD', '2026-08-05')

    def test_conflicting_same_timestamp_is_rejected_but_identical_duplicate_is_allowed(self):
        quotes = parse_boc_html(quote_page([
            ['美元', '705', '', '', '', '2026/08/05 10:00:00', '10:00:00'],
            ['美元', '706', '', '', '', '2026/08/05 10:00:00', '10:00:00'],
        ]))
        with self.assertRaisesRegex(BOCQuoteError, '冲突'):
            select_quote(quotes, 'USD', '2026-08-05')
        chosen = select_quote([quotes[0], quotes[0]], 'USD', '2026-08-05')
        self.assertEqual(chosen.rate_per_unit, Decimal('7.05'))

    def test_html_rejects_incorrect_units_wrong_columns_bad_numbers_and_bad_timestamp(self):
        valid = quote_page([['美元', '705', '700', '715', '710', '2026/08/05 10:00:00', '10:00:00']])
        for html in (
            valid.replace('单位为100外币', '单位为1外币'),
            valid.replace('<th>现汇买入价</th>', '<th>现钞买入价</th>'),
            valid.replace('<td>705</td>', '<td>NaN</td>'),
            valid.replace('<td>705</td>', '<td>0</td>'),
            valid.replace('<td>705</td>', '<td>=700+5</td>'),
            valid.replace('<td>10:00:00</td>', '<td>10:01:00</td>'),
            valid.replace('2026/08/05 10:00:00', '2026/08/32 10:00:00'),
            valid.replace('</table>', ''),
            '<html>请输入验证码</html>',
        ):
            with self.subTest(html=html[:100]):
                with self.assertRaises(BOCQuoteError):
                    parse_boc_html(html)

    def test_snapshot_is_serializable_attributed_and_uses_exact_decimal_rate(self):
        quote = select_quote(parse_boc_html(quote_page([
            ['日元', '4.226', '4.2', '4.3', '4.25', '2026/08/05 10:00:00', '10:00:00'],
        ])), 'JPY', '2026-08-05')
        snapshot = json.loads(json.dumps(quote.to_snapshot('2026-08-05')))
        self.assertEqual(snapshot['rate_cny_per_unit'], '0.04226')
        self.assertEqual(snapshot['buying_price_per_100'], '4.226')
        self.assertEqual(snapshot['quoted_unit'], 100)
        self.assertEqual(snapshot['rate_type'], '现汇买入价')
        self.assertEqual(snapshot['source']['name'], '中国银行')
        self.assertEqual(snapshot['source']['reference'], 'https://www.boc.cn/sourcedb/whpj/')
        self.assertEqual(snapshot['timezone'], 'Asia/Shanghai')
        with self.assertRaises(BOCQuoteError):
            quote.to_snapshot('2026-08-04')
        with self.assertRaises((AttributeError, TypeError)):
            quote.currency = 'EUR'

    def test_currency_mapping_rejects_unsupported_currency(self):
        for value, expected in [('美元', 'USD'), ('usd', 'USD'), ('欧元', 'EUR'), ('港币', 'HKD'), ('澳大利亚元', 'AUD'), ('美元USD', 'USD'), ('欧元 EUR', 'EUR'), ('人民币CNY', 'CNY')]:
            self.assertEqual(normalize_currency(value), expected)
        for value in ('ABC', 'BTC', '', None, '美元EUR'):
            with self.assertRaises(BOCQuoteError):
                normalize_currency(value)
        with self.assertRaises(BOCQuoteError):
            select_quote([], '人民币', '2026-08-05')

    def test_malformed_import_does_not_return_partial_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'annual.xlsx'
            for bad in ('=700+5', 'NaN', 0):
                book = Workbook()
                sheet = book.create_sheet('中行历史牌价')
                sheet.append(['货币名称', '现汇买入价', '发布时间'])
                sheet.append(['美元', '705', '2026-08-05 10:00:00'])
                sheet.append(['美元', bad, '2026-08-05 20:00:00'])
                book.save(path)
                book.close()
                with self.subTest(bad=bad):
                    with self.assertRaises(BOCQuoteError):
                        load_workbook_quotes([path])

    def test_absent_history_sheet_returns_no_records_and_does_not_change_workbook(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'annual.xlsx'
            book = Workbook()
            book.save(path)
            book.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(load_workbook_quotes([path]), [])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            with self.assertRaises(BOCQuoteUnavailableError):
                select_quote([], 'USD', '2026-08-05')

    def test_imported_date_without_seconds_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'annual.xlsx'
            book = Workbook()
            sheet = book.create_sheet('中行历史牌价')
            sheet.append(['货币名称', '现汇买入价', '发布时间'])
            sheet.append(['美元', 705, '2026-08-05'])
            book.save(path)
            book.close()
            with self.assertRaisesRegex(BOCQuoteError, '缺少完整日期或秒'):
                load_workbook_quotes([path])

    def test_official_missing_target_on_newer_page_rejects_older_candidate(self):
        pages = {
            'https://www.boc.cn/sourcedb/whpj/': quote_page([
                ['欧元', '800', '', '', '', '2026/08/05 20:00:00', '20:00:00'],
            ], page_count=2),
            'https://www.boc.cn/sourcedb/whpj/index_1.html': quote_page([
                ['美元', '705', '', '', '', '2026/08/04 20:00:00', '20:00:00'],
            ], page_count=2, page_index=1),
        }
        with patch('boc_fx_quotes.urllib.request.urlopen', side_effect=lambda request, timeout: HTMLResponse(pages[request.full_url], request.full_url)):
            with self.assertRaisesRegex(BOCCoverageError, '缺少唯一'):
                fetch_official_quotes('USD', '2026-08-05', use_cache=False)

    def test_official_page_bound_size_limit_and_page_count_change_reject_partial_data(self):
        first = quote_page([['美元', '705', '', '', '', '2026/08/05 20:00:00', '20:00:00']], page_count=2)
        second = quote_page([['美元', '704', '', '', '', '2026/08/04 20:00:00', '20:00:00']], page_count=3, page_index=1)
        def opened(request, timeout):
            return HTMLResponse(first if request.full_url.endswith('/whpj/') else second, request.full_url)
        with patch('boc_fx_quotes.urllib.request.urlopen', side_effect=opened):
            with self.assertRaises(BOCCoverageError):
                fetch_official_quotes('USD', '2026-08-05', max_pages=1, use_cache=False)
            with self.assertRaises(BOCCoverageError):
                fetch_official_quotes('USD', '2026-08-05', max_response_bytes=50, use_cache=False)
            with self.assertRaisesRegex(BOCCoverageError, '分页在读取期间改变'):
                fetch_official_quotes('USD', '2026-08-05', use_cache=False)

    def test_official_book_cache_is_shared_across_currency_and_date_requests(self):
        html = quote_page([
            ['美元', '705', '', '', '', '2026/08/05 20:00:00', '20:00:00'],
            ['欧元', '805', '', '', '', '2026/08/05 20:00:00', '20:00:00'],
        ])
        with patch('boc_fx_quotes.urllib.request.urlopen', side_effect=lambda request, timeout: HTMLResponse(html, request.full_url)) as opened:
            usd = fetch_official_quotes('美元 USD', '2026-08-05', timeout=4.123)
            eur = fetch_official_quotes('EUR', '2026-08-06', timeout=4.123)
            self.assertEqual(usd.rate_per_unit, Decimal('7.05'))
            self.assertEqual(eur.rate_per_unit, Decimal('8.05'))
            self.assertEqual(opened.call_count, 2)
            with self.assertRaisesRegex(BOCCoverageError, '缺少唯一'):
                fetch_official_quotes('HKD', '2026-08-05', timeout=4.123)
            self.assertEqual(opened.call_count, 2)

    def test_combined_timestamp_and_date_columns_agree_without_inventing_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'annual.xlsx'
            book = Workbook()
            sheet = book.create_sheet('中行历史牌价')
            sheet.append(['货币名称', '现汇买入价', '发布日期', '发布时间'])
            sheet.append(['美元USD', '705', '2026/08/05 10:00:00', '2026-08-05 10:00:00'])
            book.save(path)
            book.close()
            chosen = select_quote(load_workbook_quotes([path]), 'USD', '2026-08-05')
            self.assertEqual(chosen.published_at, dt.datetime(2026, 8, 5, 10))
            sheet.cell(2, 4).value = '2026-08-06 10:00:00'
            book.save(path)
            book.close()
            with self.assertRaises(BOCQuoteError):
                load_workbook_quotes([path])

    def test_date_only_excel_publication_cell_is_not_invented_midnight_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'annual.xlsx'
            book = Workbook()
            sheet = book.create_sheet('中行历史牌价')
            sheet.append(['货币名称', '现汇买入价', '发布时间'])
            sheet.append(['美元', '705', dt.date(2026, 8, 5)])
            book.save(path)
            book.close()
            with self.assertRaisesRegex(BOCQuoteError, '缺少发布时间'):
                load_workbook_quotes([path])

    def test_official_content_rotation_with_unchanged_page_count_is_rejected_and_not_cached(self):
        first = quote_page([
            ['美元', '705', '', '', '', '2026/08/05 20:00:00', '20:00:00'],
        ], page_count=2)
        previous = quote_page([
            ['美元', '704', '', '', '', '2026/08/04 20:00:00', '20:00:00'],
        ], page_count=2, page_index=1)
        rotated = quote_page([
            ['美元', '706', '', '', '', '2026/08/06 00:00:00', '00:00:00'],
        ], page_count=2)
        home_reads = 0
        def opened(request, timeout):
            nonlocal home_reads
            if request.full_url.endswith('/whpj/'):
                home_reads += 1
                html = first if home_reads == 1 else rotated
            else:
                html = previous
            return HTMLResponse(html, request.full_url)
        with patch('boc_fx_quotes.urllib.request.urlopen', side_effect=opened) as network:
            with self.assertRaisesRegex(BOCCoverageError, '首页在分页读取期间发生变化'):
                fetch_official_quotes('USD', '2026-08-05', timeout=4.124)
            self.assertEqual(network.call_count, 3)
            # A second explicit request must download again, never use the rejected book.
            quote = fetch_official_quotes('USD', '2026-08-06', timeout=4.124)
            self.assertEqual(quote.rate_per_unit, Decimal('7.06'))
            self.assertEqual(network.call_count, 6)


class HTMLResponse(io.BytesIO):
    def __init__(self, html, url):
        super().__init__(html.encode('utf-8'))
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = 'text/html; charset=utf-8'

    def geturl(self):
        return self.url


if __name__ == '__main__':
    unittest.main()
