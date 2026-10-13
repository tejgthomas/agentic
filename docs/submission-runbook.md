# llmHITL submission runbook

Do not create the `llmHITL` tag until every acceptance item below passes.

## 1. Create the Google iOS OAuth client

1. Sign in to Google with a personal Gmail account.
2. Open <https://console.cloud.google.com/apis/credentials>.
3. Select an existing project for this app or create one named `Agent`.
4. If prompted to configure the OAuth consent screen, enter an app name and
   support email, choose the audience appropriate for the account, and save.
5. Select **Create credentials > OAuth client ID**.
6. Choose **iOS** as the application type.
7. Enter `Agent` as the client name.
8. Enter `edu.umich.tejg.agent` as the bundle ID, matching the Xcode target
   exactly, including capitalization.
9. Create the client and download its plist.
10. Open the plist and copy the values named `CLIENT_ID` and
    `REVERSED_CLIENT_ID`.
11. Set those values as `GOOGLE_CLIENT_ID` and `GOOGLE_REVERSED_CLIENT_ID` in
    both Debug and Release configurations of the Agent target.
12. Do not create or commit a client secret; an iOS client uses these public
    identifiers and its registered bundle ID.

## 2. Prepare Xcode

1. Install the current Xcode from the Mac App Store.
2. Launch Xcode once and allow it to install required components.
3. In Terminal, select it and verify it:

   ```sh
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   xcodebuild -version
   ```

4. Open `Agent/Agent.xcodeproj`.
5. Wait for Swift Package Manager to resolve GoogleSignIn 8.0.0.
6. Select the Agent target, open **Signing & Capabilities**, select the personal
   development team, and retain bundle ID `edu.umich.tejg.agent`.
7. Confirm **Privacy - Face ID Usage Description** is present.

## 3. Trust the backend certificate

The current public certificate is copied locally to
`/Users/tej/Downloads/eecs498/harnessd.crt` and is valid for `34.56.51.226`
through October 31, 2027.

1. Boot the target iOS simulator.
2. Drag `harnessd.crt` onto the simulator window and accept the profile.
3. Open simulator **Settings > General > About > Certificate Trust Settings**.
4. Enable full trust for the UM EECS Agentic root certificate.
5. For a physical device, AirDrop or otherwise transfer the certificate, install
   the downloaded profile under **VPN & Device Management**, then enable full
   trust under **Certificate Trust Settings**.

## 4. Exercise Google Sign-In and biometrics

1. On a simulator, enable **Features > Face ID > Enrolled**.
2. Build and run Agent.
3. Dismiss the advisory reporting that no prior ticket exists.
4. Ask: `What is the weather at my location?`
5. Confirm Google Sign-In appears and completes.
6. Confirm ticket saving requests user presence.
7. Confirm the response uses the current location and returns weather.
8. Stop and relaunch the app before the ten-minute ticket expires.
9. Confirm biometric access restores the ticket without Google Sign-In.
10. Cancel a biometric prompt and confirm the protected operation does not run.
11. Wait for expiration and confirm a fresh ticket is requested rather than an
    old ticket from conversation history being reused.

## 5. Verify the backend and repository

Use the existing server key with:

```sh
ssh -i ~/.ssh/google_compute_engine -o IdentitiesOnly=yes tej@34.56.51.226
```

Then verify:

```sh
cd ~/agentic
git status --short --branch
cd harnessd
.venv/bin/python -m unittest -q test_handlers.py
sudo systemctl status harnessd
```

The branch must be clean and tracking `origin/llmHITL`, all tests must pass,
and the service must remain active.

## 6. Finalize only after acceptance

From the laptop repository:

```sh
git status --short --branch
git pull --ff-only
git tag -a llmHITL -m "Completed llmHITL"
git push origin llmHITL
git push origin refs/tags/llmHITL
```

Verify the GitHub branch and annotated tag point to the same final commit. Do not
tag a placeholder configuration or an untested iOS build.
