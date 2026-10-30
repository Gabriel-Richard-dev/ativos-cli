"""Pipeline que entrega os itens ao processo pai, um JSON por linha no stdout."""

import json
import sys


class JsonLinesStdoutPipeline:
    def process_item(self, item, spider=None):
        sys.stdout.write(json.dumps(dict(item)) + "\n")
        sys.stdout.flush()
        return item
