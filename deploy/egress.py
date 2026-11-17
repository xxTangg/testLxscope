"""Write the tool sandbox's Squid policy, then replace the process."""

import os
from pathlib import Path

policy = [
    "http_port 3128",
    "pid_filename /tmp/squid.pid",
    "acl manager proto cache_object",
    "http_access deny manager",
    "cache deny all",
    "acl failed_response http_status 400-599",
    "logformat egress_failure %ts.%03tu method=%rm status=%>Hs "
    "upstream_status=%<Hs result=%Ss error=%err_code",
    "access_log stdio:/var/log/squid/egress-failures.log "
    "egress_failure failed_response",
    "cache_store_log none",
    "cache_log /dev/stderr",
    "coredump_dir /tmp",
    "visible_hostname agentscope-egress",
    "acl forbidden dst 0.0.0.0/8 127.0.0.0/8 169.254.0.0/16 "
    "::/128 ::1/128 ::ffff:0:0/96 fe80::/10 ff00::/8 fd00:ec2::254/128",
    "http_access deny forbidden",
    "acl private dst 10.0.0.0/8 172.16.0.0/12 "
    "192.168.0.0/16 100.64.0.0/10 fc00::/7",
    "acl safe_ports port 80 443",
    "acl ssl_ports port 443",
    "acl CONNECT method CONNECT",
    "http_access deny private",
    "http_access deny !safe_ports",
    "http_access deny CONNECT !ssl_ports",
    "http_access allow all",
]
Path("/etc/squid/squid.conf").write_text("\n".join(policy) + "\n")
os.execvp("squid", ["squid", "-N", "-f", "/etc/squid/squid.conf"])
