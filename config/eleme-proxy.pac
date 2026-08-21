function FindProxyForURL(url, host) {
  var normalizedHost = String(host || "").toLowerCase();
  if (
    normalizedHost === "ele.me" ||
    dnsDomainIs(normalizedHost, ".ele.me") ||
    normalizedHost === "elemecdn.com" ||
    dnsDomainIs(normalizedHost, ".elemecdn.com")
  ) {
    return "SOCKS5 127.0.0.1:18887";
  }
  return "DIRECT";
}
