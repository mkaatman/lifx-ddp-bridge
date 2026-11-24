#!/usr/bin/env bash
# Regenerate the Node-RED flow from build_flow.py + chandelier_bulbs.json and deploy it in place.
#   ./deploy.sh            (NODERED_HOST defaults to root@192.168.2.143)
set -euo pipefail
cd "$(dirname "$0")"
HOST="${NODERED_HOST:-root@192.168.2.143}"
TAB="9ca251a1cf3b1707"        # "DDP → LIFX LAN" tab id on Node-RED

python3 build_flow.py
ssh -o BatchMode=yes "$HOST" 'mkdir -p /root/ddp-deploy'
scp -q flows/ddp-lifx-lan.json chandelier_bulbs.json "$HOST:/root/ddp-deploy/"
ssh -o BatchMode=yes "$HOST" "set -e
export PATH=\$(ls -d /root/.nvm/versions/node/*/bin | tail -1):\$PATH
cd /root/ddp-deploy && mv ddp-lifx-lan.json new.json
node -e '
const d=require(\"./new.json\");
for (const n of d.nodes) if (n.type===\"function\") for (const k of [\"initialize\",\"func\",\"finalize\"]) if (n[k])
  new Function(\"msg\",\"node\",\"context\",\"dgram\",\"async function x(){\"+n[k]+\"\n}\");
console.log(\"syntax ok\")'
cp ~/.node-red/flows.json ~/.node-red/flows.json.pre-deploy-\$(date +%Y%m%d%H%M%S)
curl -sf -X PUT -H 'Content-Type: application/json' --data @new.json http://127.0.0.1:1880/flow/$TAB
echo
sleep 3; journalctl -u nodered --since '-15s' --no-pager | grep -iE 'error|warn' || echo 'deployed, no errors'"
