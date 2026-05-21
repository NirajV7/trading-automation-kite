# iOS Shortcuts: Emergency Panic Kill Switch Setup

This guide explains how to configure a native widget on your iPhone's home screen to instantly execute the emergency panic kill switch (canceling all open orders and squaring off all active positions on Zerodha Kite) over your Tailscale VPN.

---

## Prerequisites
1. **Tailscale App**: Ensure Tailscale is installed on both your iPhone and the host machine running the backend (Dell G15 server), and both are connected to the same Tailnet.
2. **IP Address**: Note down the Tailscale IP of your Dell G15 machine (e.g., `100.x.y.z`).

---

## Step-by-Step Configuration

1. Open the **Shortcuts** app on your iPhone.
2. Tap the **`+`** (plus) icon in the top right to create a new shortcut.
3. Rename the shortcut to **`Panic Kill Switch`** or **`Kite Exit All`**.
4. Tap **Add Action**.
5. Search for **URL** (under Web) and add it:
   - Enter: `http://<YOUR_DELL_G15_TAILSCALE_IP>:8080/api/kite/panic`
6. Tap the search bar at the bottom, search for **Get Contents of URL** (under Web), and add it:
   - Change the Method from **GET** to **POST**.
   - Leave the Headers and Request Body empty.
7. Tap the search bar at the bottom, search for **Show Result** or **Speak Text** (to receive audible/visual confirmation on execution success), and add it:
   - Input: **Contents of URL** (or raw response message).
8. Tap **Done** to save the shortcut.

---

## Home Screen Widget Setup

1. Go to your iPhone home screen, tap and hold an empty space until the apps jiggle.
2. Tap the **`+`** icon in the top-left corner.
3. Search for **Shortcuts**, select the widget style you prefer, and tap **Add Widget**.
4. Tap the widget to select your **Panic Kill Switch** shortcut.
5. Tap anywhere to save.

*When clicked, this widget will instantly send a secure POST request over your private Tailscale VPN to the FastAPI backend, executing a full order cancellation and position square-off.*
