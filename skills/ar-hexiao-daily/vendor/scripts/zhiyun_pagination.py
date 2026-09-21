"""One pagination completeness contract for Zhiyun list and relation reads."""
from __future__ import annotations

class PageAccumulator:
    def __init__(self, page_size, error_type, max_pages=500):
        if page_size <= 0 or max_pages <= 0:
            raise error_type("取数分页参数必须为正数")
        self.page_size=page_size
        self.error_type=error_type
        self.max_pages=max_pages
        self.rows=[]
        self.total=None
        self.pages=0
        self.seen_pages=set()

    def accept(self, response, *, relation=False):
        total=None
        if isinstance(response, list):
            batch=response
        elif isinstance(response, dict):
            batch=response.get('data')
            if relation and batch is None:
                batch=response.get('rows')
            if relation and isinstance(batch, dict):
                batch=batch.get('data')
            raw_total=response.get('count')
            if raw_total not in (None, ''):
                try:
                    total=int(str(raw_total))
                except (TypeError, ValueError):
                    raise self.error_type("接口返回的总条数不是有效整数") from None
                if total < 0:
                    raise self.error_type("接口返回负的总条数")
        else:
            batch=None
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise self.error_type("接口返回的数据页结构异常，不能视为没有记录")
        if total is not None:
            if self.total is not None and total != self.total:
                raise self.error_type("翻页过程中总条数变化，本次取数不完整")
            self.total=total
        keys=tuple(str(row.get('rowid') or row.get('id') or '') for row in batch)
        if keys and all(keys):
            if keys in self.seen_pages:
                raise self.error_type("接口重复返回同一数据页，本次取数不完整")
            self.seen_pages.add(keys)
        self.pages+=1
        self.rows.extend(batch)
        if self.total is not None:
            if len(self.rows)>self.total:
                raise self.error_type("取回条数超过接口总条数，本次取数不一致")
            if len(self.rows)==self.total:
                return True
            if not batch:
                raise self.error_type("接口提前返回空页，尚未取全声明的记录")
        elif len(batch)<self.page_size:
            return True
        if self.pages>=self.max_pages:
            raise self.error_type("取数达到分页安全上限但尚未完成，不能使用截断结果")
        return False
