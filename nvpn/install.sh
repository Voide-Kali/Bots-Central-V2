#!/bin/bash
set -e
install -d "${1:-/usr/local/bin}"
install -m 755 nvpn "${1:-/usr/local/bin}/"
