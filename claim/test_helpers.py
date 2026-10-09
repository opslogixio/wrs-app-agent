"""Read rendered queue tables for regression and deployment verification."""
from html.parser import HTMLParser


class QueueTableParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tables = {}
        self.table = self.row = self.cell = None
        self.in_body = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            name = attrs.get('id')
            self.table = name if name in {'bodyshopTable', 'claimsTable'} else None
            if self.table:
                if self.table in self.tables:
                    raise AssertionError(f'Duplicate queue table ID: {self.table}')
                self.tables[self.table] = []
        elif self.table and tag == 'tbody':
            self.in_body = True
        elif self.table and self.in_body and tag == 'tr':
            self.row = {'cells': [], 'links': []}
        elif self.row is not None and tag == 'td':
            self.cell = []
        elif self.row is not None and tag == 'a':
            self.row['links'].append(attrs.get('href', '').strip())

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            self.row['cells'].append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.tables[self.table].append(self.row)
            self.row = None
        elif tag == 'tbody':
            self.in_body = False
        elif tag == 'table':
            self.table = None
