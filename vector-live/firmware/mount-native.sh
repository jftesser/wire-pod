#!/bin/sh
# Exact-version, hash-pinned application overlay; normal wake-word mode stays available.
set -eu
[ "$(getprop ro.serialno)" = 00a14a38 ]
[ "$(cat /etc/os-version)" = 3.0.2.36d ]
[ "$(cat /etc/victor-compat-version)" = 209 ]
app=/data/vector-native-mic/application-36d
[ -f "$app/etc/vector-continuous-mic-experiment" ]
cd "$app"
sha256sum -c <<'NATIVE_HASHES'
6a538cd69e15f65cdb0de1bc133b50be46b793975ad4a25e1426cca30aa3edd4  bin/vic-anim
118586cf91fb1ccf29dea98ae46fbf77f1c9d24c9d5d760555d235ee0b730a82  bin/vic-engine
235cde091c9489ac88bb478185e7641deb173a97ecc9717b3c23125ed4dd90b4  bin/vic-cloud
27c5dd20b0354d55dc9595799ba635562fcc663f10437f43fcd011597591d7cd  lib/libcozmo_engine.so
9766de81e83b927215c0cf326373d4eafdce470a68b58cfb43e722d1cf8196c8  lib/libaudio_engine.so
4ade5719183212ca204b82dfd2241f5ecf45aa643b1583d4f5f4f4f1914c8bf4  lib/libvictor_web_library.so
cc94996e87eb485409429a6da11975033c6f58175b76d1e6b896338503b4cc5c  lib/libwhiskeyToF.so
084f60c3559a894b81acef91158e5486cfee2d053097361384df43318caf4722  lib/libcameraService.so
c48ccb5dd5295e99ac296508525e2fdab330f7d5a2bb900c8e29c5ea0cc33a82  lib/libcubeBleClient.so
NATIVE_HASHES
if [ ! -f /anki/etc/vector-continuous-mic-experiment ]; then
 cd /anki
 sha256sum -c <<'STOCK_HASHES'
964032810a2268a48d1e968d02954c55b0e0f5a17e800212060bf505bea1c34f  bin/vic-anim
c2821e01702c50a60b04ed918267a5f567093df3d9abe2beaabcee58fb4bc232  bin/vic-engine
277fbadabf437d8e3310b6736cd13903ed7f16137a63de614477b87acad2b22a  bin/vic-cloud
cfd818aa5585ae2480fd67c8c88906ea04b91825b9e23500c4587f7bcc18be00  lib/libcozmo_engine.so
29da7fae0462c440b272f862b5b13afcf4c1c80c29d8107c077348e6102258ef  lib/libaudio_engine.so
05572ea283954a2fe8a80f2690b09b3543f54128b7bde4bae3d414177da0bee6  lib/libvictor_web_library.so
86519a871381d0e2b65e0fa07b9c85be9566d87d147badc651ac7e6f95636f09  lib/libwhiskeyToF.so
9a60b2e2d348c87b2664131534d29823c391eb74c4657ccafd827f59d3513441  lib/libcameraService.so
ef8b9b44f8e9f8aba109a21f10e6000d7e9e48ced18b42f2e34b44aa26a26e08  lib/libcubeBleClient.so
STOCK_HASHES
 mount --bind "$app" /anki
fi
mount -o remount,bind,ro /anki
