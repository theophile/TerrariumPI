---
title: Remote relay
categories: [Hardware, Relay]
tags: [relay, remote]
permalink: /hardware/relay/:title/

image:
  src: /assets/img/REST_API.webp
  alt: "Remote relay (API)"

device_type : Remote power switch (API)
device_address: http(s)://some.domain.com/path/location/script.php
---

## Information
This is a remote dimmer that works with GET and POST (not yet) actions on a HTTP server. It uses the default [remote data format]({{ 'faq/remote_data/' | relative_url}})

{% include_relative _relay_detail.md %}