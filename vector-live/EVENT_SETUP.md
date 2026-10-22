# Event setup: Vector and Goth Duck

## Onsite network · October 22, 2026

The venue setup now uses the Pi itself as Vector's private access point:

`UUFCO Guest → Mac Wi-Fi → Internet Sharing / USB Ethernet → Pi → VectorTable Wi-Fi → Vector`

- Mac Ethernet adapter: `en14`, shared through `bridge100`.
- Pi Ethernet address: `192.168.2.2`; admin:
  `http://192.168.2.2:8080/vector-live.html`.
- Pi private Wi-Fi: **VectorTable**, WPA2-CCMP, 2.4 GHz channel1,
  `192.168.77.1/24`. Vector currently has `192.168.77.232`.
- NetworkManager profile `vector-table-private` autoconnects at priority100.
  The venue-client profile `vector-event-uufco-guest` remains saved with
  autoconnect disabled. Original home profiles are preserved.
- The generated Wi-Fi password is stored privately on the Pi and in its
  NetworkManager profile; no password or API key belongs in this document.

Both devices joined UUFCO Guest, but Vector's SSH/SDK ports timed out from the
Pi, including in a clean Wi-Fi-only test with Ethernet disconnected. They became
reachable immediately on VectorTable. Guest peer filtering is the likely cause;
the venue's router policy was not inspected.

The venue and Mac Internet Sharing both use `192.168.2.0/24`. The owner applied
this temporary host route so return traffic to the Pi uses Ethernet:

```sh
sudo route -n delete -host 192.168.2.2
sudo route -n add -host 192.168.2.2 -interface bridge100
```

This route may need reapplying after a Mac restart or network/share changes.
Verify the Pi's actual lease and bridge before reusing it. Stopping Sharing
removed the Mac's Wi-Fi subnet route during the overlap test; renewing the
Wi-Fi DHCP lease restored it. No administrator password was collected by the
companion. Keep the Mac awake, online and connected to the Pi by Ethernet;
the Mac need not join VectorTable. A distinct Ethernet sharing subnet would
be a cleaner long-term setup; that preference was not changed onsite.

Validation: Pi OpenAI HTTPS returned401 without credentials, confirming network
reachability. Vector's existing SSH host key and developer key authenticated
through the Pi; the native microphone overlay is active. Authenticated SDK
status confirmed serial00a14a38, WireOS3.0.2.35d and the new private address.
The stale home address in wire-pod's pairing metadata was updated without
changing tokens. A private backup is at
`/home/pi/vector-native-backups/20261022-before-private-network/botSdkInfo.json`.
The admin is reachable with Live off; saved personality/sound/motion settings
are preserved. No paid conversation was opened for these network checks.
The ordinary clock and attended Live rehearsal remain separate checks.

The Bluetooth setup site's non-EP warning checks whether the version string
contains `ep`; it does not recognize WireOS. Its normal-mode path shows the
warning and activation screen without starting an OTA. Wi-Fi was changed
through its existing Bluetooth terminal (`wifi-scan`, `wifi-connect`,
`wifi-ip`, `status`), then Bluetooth was disconnected. No recovery mode,
activation, erasure or firmware replacement was performed. Reloading the
setup page cleared its temporary command history after configuring Wi-Fi.

## Pre-event recommendation

Bring the **known-working Pi, Mac, Duck and a private 2.4 GHz router**. Rehearse on
that same router before leaving; change only its Internet uplink at the venue.
This currently needs less migration work than Mac-only, despite the extra box.

```mermaid
flowchart LR
  Internet[Venue Internet uplink] --> Router[Private router · stable SSID]
  Router -- Ethernet --> Pi[Pi · wire-pod and Vector Live]
  Router -- 2.4 GHz Wi-Fi --> Vector[Vector]
  Router -- LAN or Wi-Fi --> Mac[Mac · operator consoles]
  Mac -- USB --> Duck[Goth Duck]
  Pi -- native mic and Live speaker stream --> Vector
```

Before the onsite migration, the Pi used Ethernet with Wi-Fi disconnected. Its services,
pairing, certificates and rollback already work. Duck uses USB for input/output
and needs no additional Wi-Fi provisioning.

## Pi versus Mac

| Option | Proven foundation | Additional work |
|---|---|---|
| Pi wire-pod and Vector Live; Mac Duck | Native microphone, ARM echo processor and local controller deployed; Duck supports USB on Mac | Pi-only voice confirmation and shared acoustic rehearsal; see migration results |
| Pi wire-pod; Mac both voice companions | Separate Duck USB and Vector Wi-Fi transports; host mic pipeline passes offline tests | Choose microphone; rehearse both agents and echo cancellation |
| Mac everything | wire-pod source supports macOS; Mac is arm64 | Install/rehearse Mac wire-pod and libraries; safely migrate pairing/certs; check discovery, privileged ports and recovery |

There is no inherent port or USB ownership conflict between Duck and Vector.
Use separate Python environments because Vector pins older protobuf. Keep the
Duck serial port owned by one process. **Simultaneous acoustic operation is not
tested:** agents can hear and answer one another even with sufficient CPU/network.
Use each robot's own microphone near its participant and rehearse cross-talk.

## Prepare at home

1. Configure a stable private SSID/password and compatible 2.4 GHz Wi-Fi. Disable
   AP/client isolation. Vector cannot complete a captive portal.
   [Manufacturer requirements](https://support.anki.bot/article/104-troubleshooting-vectore28099s-connection).
2. Connect Pi by Ethernet and Mac to the same LAN. Provision Vector's Wi-Fi with
   the existing Bluetooth/web setup while preserving data/pairing. Do not erase
   the robot merely to change Wi-Fi.
3. Reserve DHCP addresses if possible. Choose a LAN subnet that differs from the
   venue uplink; do not depend on current home addresses10.0.0.212/10.0.0.91.
4. Verify `escapepod.local` resolves to Pi. EP firmware uses that hostname, so
   mDNS or LAN DNS must resolve it. Run one advertiser when evaluating Mac-only.
   [Maintainer explanation](https://github.com/kercre123/wire-pod/issues/335#issuecomment-2147942565).
5. Test OpenAI connectivity from the host over HTTPS/WebSocket. A working local
   clock command or reachable admin page does not prove cloud voice connectivity.
6. Cold-boot the complete setup on the private router and repeat the rehearsal.

Local source confirms wire-pod updates paired robot addresses from the robot's
`_ankivector._tcp` advertisement; this has not been tested on a new LAN yet.
The Mac bridge now accepts `--ssh-target` and defaults to `escapepod.local` rather
than a home-only IP. The Pi companion uses127.0.0.1 for its local wire-pod connection.

## Arrival

- Power the router, establish its uplink and handle any venue login on the
  uplink side using an operator device. Then power Pi and Vector's charger.
- Join Mac to the private LAN. Open [wire-pod](http://escapepod.local:8080) and
  [Vector Voice](http://escapepod.local:8080/vector-live.html); confirm robot,
  mode and microphone source before starting.
- In the existing Duck project run `uv run --locked python -m gothduck`; open
  [Duck's console](http://127.0.0.1:8787). Confirm USB port/input device before joining.
- Test each agent alone, then together: ordinary speech, interruption, speaker
  echo, start/stop, USB reconnect and brief Internet loss. Rehearse30–60 minutes
  at intended seating distance and volume. Keep Mac powered/awake for its services.
- End paid sessions during breaks. Muting input does not close the cloud connection.

## Continuous listening on the Pi

The custom WireOS application now supplies Vector's real internal microphones.
The Pi-native controller, echo worker and cloud transport remove the Mac
requirement for Vector. The Mac still runs Duck over USB. Voice stays off until
explicit web-admin Start; the idle controller can run across boots. See
[PI_MIGRATION.md](PI_MIGRATION.md) for the current deployment and measured results.

The original host-microphone prototype remains available as development fallback.
It is no longer the intended event microphone path. Echo delay and interference
between Duck and Vector still need rehearsal in the intended room arrangement.

## Optional physical controls

Use the web admin as the primary control for the event. The companion already
listens for a sustained back-touch rise as a stop request; its threshold and
timing still need a physical rehearsal. It does not start sessions from touch.
Losing the robot-state event stream closes the session rather than dropping the
stop control silently.

A double tap is the preferred next optional start/stop gesture: measure the
untouched baseline, use hysteresis and about60 ms debounce, require two short
press/release cycles within roughly600 ms, then apply a two-second cooldown.
Those values are proposed tuning, not measured reliability. An idle state-only
watcher could start the same controller, with no movement commands; keep that
watcher disabled until rehearsed so casual handling does not open a paid session.

Arm lift/lower is lower priority. We would need to distinguish deliberate manual
patterns from normal arm animation using measured lift-angle events. That path
has not been calibrated or implemented. It adds event-demo complexity without
improving on the web control enough to justify making it the first choice.
