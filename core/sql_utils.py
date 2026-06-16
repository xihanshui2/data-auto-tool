def quote_identifier(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'
