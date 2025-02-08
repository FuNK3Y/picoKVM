# picoKVM
An inexpensive network KVM that can switch USB and monitor inputs simultaneously

## Why
Samsung makes great monitor, but they often lack a KVM. This project's ambition is to take advantage of the smart features of those monitors to build one with unique features.

## Features
The networking enable some unique features:
- It can control as many monitor as you can connect to your computers, as long as those can be driven over IP
- Monitor signal is not subject to any degradation, as every computer is connected directly to each monitor
- Other devices can be controlled as well - provided they can be driven by IP
    - You could for instance switch the color of a lamp - based on the selected input of the KVM
- HDCP, VRR, G-Sync, FreeSync, HDR, ... all works natively without gimmick such as EDID emulation - because every computer is directly connected to every monitor
- You can control the KVM from any device on the same network (phone, tablet, computer, ...)

## How does it works
The Pico will uses the Samsung remote API (https://samsungtv:8002/api/v2/) to inject key presses in order to change inputs. As on my monitor (G80SD) there is sadly no key directly mapped to inputs (like KEY_DISPLAYPORT, KEY_HDMI1). I had to build a sequence of key presses starting from the home screen. The interface is snappy enough to smoothen up this downside.

Another alternative would be to use the [SmartThings REST API](https://github.com/ollo69/ha-samsungtv-smart/issues/274#issuecomment-2597627685) - as this API allows for direct input selection. 

## Hardware setup
In order to get this project working you need at least the following components:
- [A Raspberry Pi Pico 2 W](https://thepihut.com/products/raspberry-pi-pico-2-w)
- [A USB multiplexer](https://thepihut.com/products/bidirectional-usb-3-multiplexer)

They needs to be wired together (3V3, Ground, Signal over GPIO)

## Software setup
Clone localy this repo and copy the files of this repository to your pico ([Thonny](https://thonny.org/) works great for that). On top you need to install the additional package `aiottp` (this can be done with Thonny as well). Applying [this optional fix](https://github.com/micropython/micropython-lib/pull/972) will greatly increases performance in some scenarios.

Adjust `config.json` with your settings. You need to configure at least your Wi-Fi credentials and the GPIO pin you connected the signal cable from the USB multiplexer to.

Then, you need to configure your monitor. Either make sure that `Connection > Network > Expert Settings > IP Remote : Enabled` or configure SmartThings

### Samsung Remote API
Using your remote, find a repeatable pattern of key presses that will allow you to select the correct input. Then, using the [key code reference](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_codes.md), adjust `config.json` accordingly.

The pattern will be different for every input (`A` & `B`).

### Example:
```json
"command_sequences": {
    "A": [
        "KEY_HOME",
        "KEY_LEFT",
        "KEY_DOWN",
        "KEY_RIGHT",
        "KEY_ENTER"
    ],
    "B": [
        "KEY_HOME",
        "KEY_LEFT",
        "KEY_DOWN",
        "KEY_RIGHT",
        "KEY_RIGHT",
        "KEY_ENTER"
    ]
}
```
You can finally fine-tune the delay between each command to make sure the interface can keep track of those (`command_delay`).

If the monitor is not powered on during an input switch, it will be automatically turned on so that commands can be registered.

### SmartThings API
I did not try it, but creating a device of type `GenericDevice` with [this payload](https://github.com/ollo69/ha-samsungtv-smart/issues/274#issuecomment-2597627685) should work fine.

### Example:
```json
{
    "data": {
        "uri": "https://api.smartthings.com/v1/devices/deviceId/commands",
        "method": "POST",
        "kwargs": {
            "A": {
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer token"
                },
                "data": "{\"commands\":[{\"component\":\"main\",\"capability\":\"samsungvd.mediaInputSource\",\"command\":\"setInputSource\",\"arguments\":[\"Display Port\"]}]}"
            },
            "B": {
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer token"
                },
                "data": "{\"commands\":[{\"component\":\"main\",\"capability\":\"samsungvd.mediaInputSource\",\"command\":\"setInputSource\",\"arguments\":[\"HDMI1\"]}]}"
            }
        }
    },
    "type": "GenericDevice"
}
```

## How to use
Here is how to connect everything together:
- Connect computers directly to the monitors
- Connect USB from the computers to the KVM
- Connect keyboard & mouse to a USB switch - itself connected to the KVM
    - The primary monitor should be used as a USB hub (as shown in the schema). In the case of the G80SD it retains the capability to drive the smart features of the monitor with the keyboard & mouse

### Schema
```mermaid
graph LR
    KB["Keyboard"] <--> |USB| MON
    MOUSE["Mouse"] <--> |USB| MON
    KVM <--> |USB| MON
    PC1["Computer 1"] --> |HDMI/DisplayPort| MON["Monitor"]
    PC2["Computer 2"] --> |HDMI/DisplayPort| MON
    PC1 <--> |USB| KVM["picoKVM"]
    PC2 <--> |USB| KVM
    style MON fill:#f9f,stroke:#333
    style KVM fill:#bbf,stroke:#333
    style KB fill:#ddd,stroke:#333
    style MOUSE fill:#ddd,stroke:#333
    style PC1 fill:#ddd,stroke:#333
    style PC2 fill:#ddd,stroke:#333
```
Currently, there are two ways to operate the KVM. You need to know the IP address until the mDNS discovery issue is sorted out.

### Web page
Simply connect to `http://ip_address` and press the only button.

### API
Issue a `POST` request to `http://ip_address/api/set_active_input/A` or `B`.

**_NOTE:_** If the input name is omitted, it will act as a toggle.

#### PowerShell example:
```powershell
Invoke-WebRequest -Method POST "http://ip_address/api/set_active_input/A"
```

## Next steps
- Find a nice hardware button for easier input switching.
- 3D print a case to hold everything together.
- Support mDNS for easy discovery - apparently stuck on [this issue](https://github.com/micropython/micropython/pull/16641).

## Roadmap
- [ ] Hardware button integration for physical input switching
- [ ] 3D printable case design
- [ ] mDNS support (blocked by [micropython#16641](https://github.com/micropython/micropython/pull/16641))
