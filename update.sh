#!/bin/bash
cd /workspace/alight-status
A=/workspace/alight-analysis; W=/workspace/alight-web
st(){ [ "$1" = 1 ] && echo done || { [ "$2" = 1 ] && echo run || echo todo; }; }
apk=$([ -f $A/base.apk ] && echo 1)
dec=$([ -d $A/apktool-out ] && echo 1)
jr=$(pgrep -f JadxCLI >/dev/null && echo 1); jd=$([ -d $A/jadx-out ] && [ -z "$jr" ] && echo 1)
fd=$([ -f $A/FINDINGS.md ] && echo 1)
wn=$(find $W -type f 2>/dev/null | wc -l); wb=$([ $wn -gt 0 ] && echo 1)
sh=$(ls $W/*.png $W/screens/*.png 2>/dev/null | head -1)
pub=$(gh repo view sfxhewitt/motion-web >/dev/null 2>&1 && echo 1)
cat > status.json <<J
{"updated":"$(date '+%H:%M:%S %Z')","steps":[
{"name":"Download official APK","state":"$(st "$apk")"},
{"name":"Decode resources (apktool)","state":"$(st "$dec")"},
{"name":"Decompile code (JADX)","state":"$(st "$jd" "$jr")"},
{"name":"Write findings","state":"$(st "$fd" "$jd")"},
{"name":"Build web app ($wn files)","state":"$(st "$([ -n "$sh" ] && echo 1)" "$wb")"},
{"name":"Test on desktop + iPhone sizes","state":"$(st "$([ -n "$sh" ] && echo 1)")"},
{"name":"Publish to GitHub Pages","state":"$(st "$pub")"}]}
J
git add -A && git commit -qm status >/dev/null 2>&1 && git push -q 2>/dev/null
