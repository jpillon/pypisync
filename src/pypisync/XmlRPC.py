import xmlrpc.client
import http.client
import os
import logging


logger = logging.getLogger(__name__)


class ProxiedTransport(xmlrpc.client.SafeTransport):
    def __init__(self, use_datetime=False, use_builtin_types=False,
                 *, headers=(), proxy=None):
        try:
            super().__init__(use_datetime=use_datetime,
                             use_builtin_types=use_builtin_types,
                             headers=headers)
        except TypeError:
            # Backward compatibility for older python
            super().__init__(use_datetime=use_datetime,
                             use_builtin_types=use_builtin_types)
        self.proxy = proxy
        if self.proxy is not None:
            while self.proxy.endswith("/"):
                self.proxy = self.proxy[:-1]
            while self.proxy.startswith("http://"):
                self.proxy = self.proxy[7:]
            while self.proxy.startswith("https://"):
                self.proxy = self.proxy[8:]
        self.real_host = None

    def make_connection(self, host):
        if self.proxy is None:
            return super().make_connection(host)
        self.real_host = host
        h = http.client.HTTPConnection(self.proxy)
        return h

    def send_request(self, host, handler, request_body, debug):
        if self.proxy is not None:
            handler = 'http://%s%s' % (self.real_host, handler)
        return super().send_request(host, handler, request_body, debug)


def get_xmlrpc_server_proxy(
        uri,
        transport=None,
        encoding=None,
        verbose=False,
        allow_none=False,
        use_datetime=False,
        use_builtin_types=False,
        *,
        headers=(),
        context=None
):
    if transport is not None:
        logger.error("transport is ignored as it is replaced by ProxiedTransport")
    p = ProxiedTransport(
        proxy=os.environ.get("HTTP_PROXY", None),
        use_datetime=False,
        use_builtin_types=False,
        headers=(),
    )
    try:
        return xmlrpc.client.ServerProxy(
            uri,
            transport=p,
            encoding=encoding,
            verbose=verbose,
            allow_none=allow_none,
            use_datetime=use_datetime,
            use_builtin_types=use_builtin_types,
            headers=headers,
            context=context
        )
    except TypeError:
        return xmlrpc.client.ServerProxy(
            uri,
            transport=p,
            encoding=encoding,
            verbose=verbose,
            allow_none=allow_none,
            use_datetime=use_datetime,
            use_builtin_types=use_builtin_types,
            context=context
        )


# TODO: Maybe use another lib for proxy compatibility (like xmlrpclibex)
ServerProxy = get_xmlrpc_server_proxy
