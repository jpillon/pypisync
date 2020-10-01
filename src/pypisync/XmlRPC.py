import xmlrpc.client
import http.client
import gzip
import os
import logging


logger = logging.getLogger(__name__)


class ProxiedTransport(xmlrpc.client.SafeTransport):
    def set_proxy(self, proxy):
        self.proxy = proxy
        if self.proxy is not None:
            while self.proxy.endswith("/"):
                self.proxy = self.proxy[:-1]
            while self.proxy.startswith("http://"):
                self.proxy = self.proxy[7:]
            while self.proxy.startswith("https://"):
                self.proxy = self.proxy[8:]

    def make_connection(self, host):
        if self.proxy is None:
            return super().make_connection(host)
        self.real_host = host
        h = http.client.HTTPConnection(self.proxy)
        return h

    def send_request(self, host, handler, request_body, debug):
        if self.proxy is None:
            return super().send_request(host, handler, request_body, debug)
        connection = self.make_connection(host)
        headers = self._extra_headers[:]
        new_handler = 'http://%s%s' % (self.real_host, handler)
        if debug:
            connection.set_debuglevel(1)
        if self.accept_gzip_encoding and gzip:
            connection.putrequest("POST", new_handler, skip_accept_encoding=True)
            headers.append(("Accept-Encoding", "gzip"))
        else:
            connection.putrequest("POST", new_handler)
        headers.append(("Content-Type", "text/xml"))
        headers.append(("User-Agent", self.user_agent))
        self.send_headers(connection, headers)
        self.send_content(connection, request_body)
        return connection


def get_xmlrpc_server_proxy(
        uri,
        transport=None,
        encoding=None,
        verbose=False,
        allow_none=False,
        use_datetime=False,
        use_builtin_types=False,
        *args,
        headers=(),
        context=None
):
    if transport is not None:
        logger.error("transport is ignored as it is replaced by ProxiedTransport")
    p = ProxiedTransport()
    p.set_proxy(os.environ.get("HTTP_PROXY", None))
    return xmlrpc.client.ServerProxy(
        uri,
        transport=p,
        encoding=encoding,
        verbose=verbose,
        allow_none=allow_none,
        use_datetime=use_datetime,
        use_builtin_types=use_builtin_types,
        *args,
        headers=headers,
        context=context
    )


ServerProxy = get_xmlrpc_server_proxy