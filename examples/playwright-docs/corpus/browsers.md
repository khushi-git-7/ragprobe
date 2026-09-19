# Browsers

## Introduction

Each version of Playwright needs specific versions of browser binaries to operate. You will need to use the Playwright CLI to install these browsers.

With every release, Playwright updates the versions of the browsers it supports, so that the latest Playwright would support the latest browsers at any moment. It means that every time you update Playwright, you might need to re-run the `install` CLI command.

## Install browsers

Playwright can install supported browsers. Running the command without arguments will install the default browsers.

```bash
npx playwright install
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
playwright install
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install
```

You can also install specific browsers by providing an argument:

```bash
npx playwright install webkit
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install webkit"
```

```bash
playwright install webkit
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install webkit
```

See all supported browsers:

```bash
npx playwright install --help
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install --help"
```

```bash
playwright install --help
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install --help
```

### Install browsers via API

It's possible to run Command line tools commands via the .NET API:

## Install system dependencies

System dependencies can get installed automatically. This is useful for CI environments.

```bash
npx playwright install-deps
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install-deps"
```

```bash
playwright install-deps
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install-deps
```

You can also install the dependencies for a single browser by passing it as an argument:

```bash
npx playwright install-deps chromium
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install-deps chromium"
```

```bash
playwright install-deps chromium
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install-deps chromium
```

It's also possible to combine `install-deps` with `install` so that the browsers and OS dependencies are installed with a single command.

```bash
npx playwright install --with-deps chromium
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install --with-deps chromium"
```

```bash
playwright install --with-deps chromium
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install --with-deps chromium
```

See [system requirements](./intro.md#system-requirements) for officially supported operating systems.

## Update Playwright regularly

By keeping your Playwright version up to date you will be able to use new features and test your app on the latest browser versions and catch failures before the latest browser version is released to the public.

```bash
# Update playwright
npm install -D @playwright/test@latest

# Install new browsers
npx playwright install
```
Check the [release notes](./release-notes.md) to see what the latest version is and what changes have been released.

```bash
# See what version of Playwright you have by running the following command
npx playwright --version
```

## Configure Browsers

Playwright can run tests on Chromium, WebKit and Firefox browsers as well as branded browsers such as Google Chrome and Microsoft Edge. It can also run on emulated tablet and mobile devices. See the [registry of device parameters](https://github.com/microsoft/playwright/blob/main/packages/isomorphic/deviceDescriptorsSource.json) for a complete list of selected desktop, tablet and mobile devices.

### Run tests on different browsers

Playwright can run your tests in multiple browsers and configurations by setting up **projects** in the config. You can also add [different options](./test-configuration) for each project.

```js
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  projects: [
    /* Test against desktop browsers */
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    /* Test against mobile viewports. */
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 12'] },
    },
    /* Test against branded browsers. */
    {
      name: 'Google Chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' }, // or 'chrome-beta'
    },
    {
      name: 'Microsoft Edge',
      use: { ...devices['Desktop Edge'], channel: 'msedge' }, // or 'msedge-dev'
    },
  ],
});
```

Playwright will run all projects by default.

```bash
npx playwright test

Running 7 tests using 5 workers

  ✓ [chromium] › example.spec.ts:3:1 › basic test (2s)
  ✓ [firefox] › example.spec.ts:3:1 › basic test (2s)
  ✓ [webkit] › example.spec.ts:3:1 › basic test (2s)
  ✓ [Mobile Chrome] › example.spec.ts:3:1 › basic test (2s)
  ✓ [Mobile Safari] › example.spec.ts:3:1 › basic test (2s)
  ✓ [Google Chrome] › example.spec.ts:3:1 › basic test (2s)
  ✓ [Microsoft Edge] › example.spec.ts:3:1 › basic test (2s)
```

Use the `--project` command line option to run a single project.

```bash
npx playwright test --project=firefox

Running 1 test using 1 worker

  ✓ [firefox] › example.spec.ts:3:1 › basic test (2s)
```

With the VS Code extension you can run your tests on different browsers by checking the checkbox next to the browser name in the Playwright sidebar. These names are defined in your Playwright config file under the projects section. The default config when installing Playwright gives you 3 projects, Chromium, Firefox and WebKit. The first project is selected by default.

![Projects section in VS Code extension](./images/vscode-projects-section.png)

To run tests on multiple projects(browsers), select each project by checking the checkboxes next to the project name.

<img src="https://github.com/microsoft/playwright/assets/13063165/6dc86ef4-6097-481c-9cab-b6e053ec7ea6" alt="Selecting projects to run tests on" width="3978" height="2294" />

### Run tests on different browsers

Run tests on a specific browser:

```bash
pytest test_login.py --browser webkit
```

Run tests on multiple browsers:

```bash
pytest test_login.py --browser webkit --browser firefox
```

Test against mobile viewports:

```bash
pytest test_login.py --device="iPhone 13"
```
Test against branded browsers:

```bash
pytest test_login.py --browser-channel msedge
```

### Run tests on different browsers

Run tests on a specific browser:

Run tests on multiple browsers and make it based on the environment variable `BROWSER`:

### Run tests on different browsers

Run tests on a specific browser:

```bash
dotnet test -- Playwright.BrowserName=webkit
```

To run your test on multiple browsers or configurations you need to invoke the `dotnet test` command multiple times. You can either specify the `BROWSER` environment variable or set the `Playwright.BrowserName` via the runsettings file:

```bash
dotnet test --settings:chromium.runsettings
dotnet test --settings:firefox.runsettings
dotnet test --settings:webkit.runsettings
```

```xml
<?xml version="1.0" encoding="utf-8"?>
  <RunSettings>
    <Playwright>
      <BrowserName>chromium</BrowserName>
    </Playwright>
  </RunSettings>
```

### Chromium

For Google Chrome, Microsoft Edge and other Chromium-based browsers, by default, Playwright uses open source Chromium builds. Since the Chromium project is ahead of the branded browsers, when the world is on Google Chrome N, Playwright already supports Chromium N+1 that will be released in Google Chrome and Microsoft Edge a few weeks later.

### Chromium: headless shell

Playwright ships a regular Chromium build for headed operations and a separate [chromium headless shell](https://developer.chrome.com/blog/chrome-headless-shell) for headless mode.

If you are only running tests in headless shell (i.e. the `channel` option is **not** specified), for example on CI, you can avoid downloading the full Chromium browser by passing `--only-shell` during installation.

```bash
# only running tests headlessly
npx playwright install --with-deps --only-shell
```

```bash
# only running tests headlessly
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install --with-deps --only-shell"
```

```bash
# only running tests headlessly
playwright install --with-deps --only-shell
```

```bash
# only running tests headlessly
pwsh bin/Debug/netX/playwright.ps1 install --with-deps --only-shell
```

### Chromium: new headless mode

You can opt into the new headless mode by using `'chromium'` channel. As [official Chrome documentation puts it](https://developer.chrome.com/blog/chrome-headless-shell):

> New Headless on the other hand is the real Chrome browser, and is thus more authentic, reliable, and offers more features. This makes it more suitable for high-accuracy end-to-end web app testing or browser extension testing.

See [issue #33566](https://github.com/microsoft/playwright/issues/33566) for details.

```js
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'chromium' },
    },
  ],
});
```

```bash
pytest test_login.py --browser-channel chromium
```

```xml
<?xml version="1.0" encoding="utf-8"?>
<RunSettings>
  <Playwright>
    <BrowserName>chromium</BrowserName>
    <LaunchOptions>
      <Channel>chromium</Channel>
    </LaunchOptions>
  </Playwright>
</RunSettings>
```

```bash
dotnet test -- Playwright.BrowserName=chromium Playwright.LaunchOptions.Channel=chromium
```

With the new headless mode, you can skip downloading the headless shell during browser installation by using the `--no-shell` option:

```bash
# only running tests headlessly
npx playwright install --with-deps --no-shell
```

```bash
# only running tests headlessly
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install --with-deps --no-shell"
```

```bash
# only running tests headlessly
playwright install --with-deps --no-shell
```

```bash
# only running tests headlessly
pwsh bin/Debug/netX/playwright.ps1 install --with-deps --no-shell
```

### Google Chrome & Microsoft Edge

While Playwright can download and use the recent Chromium build, it can operate against the branded Google Chrome and Microsoft Edge browsers available on the machine (note that Playwright doesn't install them by default). In particular, the current Playwright version will support Stable and Beta channels of these browsers.

Available channels are `chrome`, `msedge`, `chrome-beta`, `msedge-beta`, `chrome-dev`, `msedge-dev`, `chrome-canary`, `msedge-canary`.

Certain Enterprise Browser Policies may impact Playwright's ability to launch and control Google Chrome and Microsoft Edge. Running in an environment with browser policies is outside of the Playwright project's scope.

Google Chrome and Microsoft Edge have switched to a [new headless mode](https://developer.chrome.com/docs/chromium/headless) implementation that is closer to a regular headed mode. This differs from [chromium headless shell](https://developer.chrome.com/blog/chrome-headless-shell) that is used in Playwright by default when running headless, so expect different behavior in some cases. See [issue #33566](https://github.com/microsoft/playwright/issues/33566) for details.

```js
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  projects: [
    /* Test against branded browsers. */
    {
      name: 'Google Chrome',
      use: { ...devices['Desktop Chrome'], channel: 'chrome' }, // or 'chrome-beta'
    },
    {
      name: 'Microsoft Edge',
      use: { ...devices['Desktop Edge'], channel: 'msedge' }, // or "msedge-beta" or 'msedge-dev'
    },
  ],
});
```

```bash
pytest test_login.py --browser-channel msedge
```

```xml
<?xml version="1.0" encoding="utf-8"?>
<RunSettings>
  <Playwright>
    <BrowserName>chromium</BrowserName>
    <LaunchOptions>
      <Channel>msedge</Channel>
    </LaunchOptions>
  </Playwright>
</RunSettings>
```

```bash
dotnet test -- Playwright.BrowserName=chromium Playwright.LaunchOptions.Channel=msedge
```

######

Alternatively when using the library directly, you can specify the browser browserType.launch.channel when launching the browser:

#### Installing Google Chrome & Microsoft Edge

If Google Chrome or Microsoft Edge is not available on your machine, you can install
them using the Playwright command line tool:

```bash
npx playwright install msedge
```

```bash
playwright install msedge
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install msedge
```

Google Chrome or Microsoft Edge installations will be installed at the
default global location of your operating system overriding your current browser installation.

Run with the `--help` option to see a full a list of browsers that can be installed.

#### When to use Google Chrome & Microsoft Edge and when not to?

##### Defaults

Using the default Playwright configuration with the latest Chromium is a good idea most of the time.
Since Playwright is ahead of Stable channels for the browsers, it gives peace of mind that the
upcoming Google Chrome or Microsoft Edge releases won't break your site. You catch breakage
early and have a lot of time to fix it before the official Chrome update.

##### Regression testing

Having said that, testing policies often require regression testing to be performed against
the current publicly available browsers. In this case, you can opt into one of the stable channels,
`"chrome"` or `"msedge"`.

##### Media codecs

Another reason for testing using official binaries is to test functionality related to media codecs.
Chromium does not have all the codecs that Google Chrome or Microsoft Edge are bundling due to
various licensing considerations and agreements. If your site relies on this kind of codecs (which is
rarely the case), you will also want to use the official channel.

##### Enterprise policy

Google Chrome and Microsoft Edge respect enterprise policies, which include limitations to the capabilities, network proxy, mandatory extensions that stand in the way of testing. So if you are part of the organization that uses such policies, it is easiest to use bundled Chromium for your local testing, you can still opt into stable channels on the bots that are typically free of such restrictions.

### Firefox

Playwright's Firefox version matches the recent [Firefox Stable](https://www.mozilla.org/en-US/firefox/new/) build. Playwright doesn't work with the branded version of Firefox since it relies on patches.

Note that availability of certain features, which depend heavily on the underlying platform, may vary between operating systems. For example, available media codecs vary substantially between Linux, macOS and Windows.

### WebKit

Playwright's WebKit is derived from the latest WebKit main branch sources, often before these updates are incorporated into Apple Safari and other WebKit-based browsers. This gives a lot of lead time to react on the potential browser update issues. Playwright doesn't work with the branded version of Safari since it relies on patches. Instead, you can test using the most recent WebKit build.

Note that availability of certain features, which depend heavily on the underlying platform, may vary between operating systems. For example, available media codecs vary substantially between Linux, macOS and Windows. While running WebKit on Linux CI is usually the most affordable option, for the closest-to-Safari experience you should run WebKit on mac, for example if you do video playback.

## Install behind a firewall or a proxy

By default, Playwright downloads browsers from Microsoft's CDN.

Sometimes companies maintain an internal proxy that blocks direct access to the public
resources. In this case, Playwright can be configured to download browsers via a proxy server.

```bash
HTTPS_PROXY=https://192.0.2.1 npx playwright install
```

```bash
pip install playwright
HTTPS_PROXY=https://192.0.2.1 playwright install
```

```bash
HTTPS_PROXY=https://192.0.2.1 mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
HTTPS_PROXY=https://192.0.2.1 pwsh bin/Debug/netX/playwright.ps1 install
```

If the requests of the proxy get intercepted with a custom untrusted certificate authority (CA) and it yields to `Error: self signed certificate in certificate chain` while downloading the browsers, you must set your custom root certificates via the [`NODE_EXTRA_CA_CERTS`](https://nodejs.org/api/cli.html#node_extra_ca_certsfile) environment variable before installing the browsers:

```bash
export NODE_EXTRA_CA_CERTS="/path/to/cert.pem"
```

If the browser archive download is slow or stalls, you can increase the download socket timeout in milliseconds with the `PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT` environment variable. Despite its name this is an idle timeout rather than a connection timeout; it limits how long the download may go without receiving data, and defaults to 30 seconds:

```bash
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 npx playwright install
```

```bash
pip install playwright
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 playwright install
```

```bash
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000 pwsh bin/Debug/netX/playwright.ps1 install
```

If you are [installing dependencies](#install-system-dependencies) and need to use a proxy on Linux, make sure to run the command as a root user. Otherwise, Playwright will attempt to become a root and will not pass environment variables like `HTTPS_PROXY` to the linux package manager.

```bash
sudo HTTPS_PROXY=https://192.0.2.1 npx playwright install-deps
```

```bash
sudo HTTPS_PROXY=https://192.0.2.1 mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install-deps"
```

```bash
sudo HTTPS_PROXY=https://192.0.2.1 playwright install-deps
```

```bash
sudo HTTPS_PROXY=https://192.0.2.1 pwsh bin/Debug/netX/playwright.ps1 install-deps
```

## Download from artifact repository

By default, Playwright downloads browsers from Microsoft's CDN.

Sometimes companies maintain an internal artifact repository to host browser
binaries. In this case, Playwright can be configured to download from a custom
location using the `PLAYWRIGHT_DOWNLOAD_HOST` env variable.

```bash
PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 npx playwright install
```

```bash
pip install playwright
PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 playwright install
```

```bash
PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 pwsh bin/Debug/netX/playwright.ps1 install
```

It is also possible to use a per-browser download hosts using `PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST`, `PLAYWRIGHT_FIREFOX_DOWNLOAD_HOST` and `PLAYWRIGHT_WEBKIT_DOWNLOAD_HOST` env variables that
take precedence over `PLAYWRIGHT_DOWNLOAD_HOST`.

```bash
PLAYWRIGHT_FIREFOX_DOWNLOAD_HOST=http://203.0.113.3 PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 npx playwright install
```

```bash
pip install playwright
PLAYWRIGHT_FIREFOX_DOWNLOAD_HOST=http://203.0.113.3 PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 playwright install
```

```bash
PLAYWRIGHT_FIREFOX_DOWNLOAD_HOST=http://203.0.113.3 PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
PLAYWRIGHT_FIREFOX_DOWNLOAD_HOST=http://203.0.113.3 PLAYWRIGHT_DOWNLOAD_HOST=http://192.0.2.1 pwsh bin/Debug/netX/playwright.ps1 install
```

## Using a pre-installed Node.js
By default, Playwright uses its bundled Node.js runtime for operations such as browser installation and script execution. If you want Playwright to use a pre-installed Node.js binary instead of the bundled runtime, you can specify it using the `PLAYWRIGHT_NODEJS_PATH` environment variable. This can be useful in environments where you need to use a specific version of Node.js or where the bundled runtime is not compatible.

```bash
PLAYWRIGHT_NODEJS_PATH="/usr/local/bin/node" npx playwright install
```

```bash
pip install playwright
PLAYWRIGHT_NODEJS_PATH="/usr/local/bin/node" playwright install
```

```bash
PLAYWRIGHT_NODEJS_PATH="/usr/local/bin/node" mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
PLAYWRIGHT_NODEJS_PATH="/usr/local/bin/node" pwsh bin/Debug/netX/playwright.ps1 install
```

## Managing browser binaries

Playwright downloads Chromium, WebKit and Firefox browsers into the OS-specific cache folders:

- `%USERPROFILE%\AppData\Local\ms-playwright` on Windows
- `~/Library/Caches/ms-playwright` on macOS
- `~/.cache/ms-playwright` on Linux

These browsers will take a few hundred megabytes of disk space when installed:

```bash
du -hs ~/Library/Caches/ms-playwright/*
281M  chromium-XXXXXX
187M  firefox-XXXX
180M  webkit-XXXX
```

You can override default behavior using environment variables. When installing Playwright, ask it to download browsers into a specific location:

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers npx playwright install
```

```bash
pip install playwright
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers python -m playwright install
```

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install"
```

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers pwsh bin/Debug/netX/playwright.ps1 install
```

When running Playwright scripts, ask Playwright to search for browsers in a shared location.

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers npx playwright test
```

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers python playwright_script.py
```

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers mvn test
```

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers dotnet test
```

Playwright keeps track of packages that need those browsers and will garbage collect them as you update Playwright to the newer versions.

Developers can opt into this mode by exporting `PLAYWRIGHT_BROWSERS_PATH=$HOME/pw-browsers` in their `.bashrc`.

### Hermetic install

You can opt into the hermetic install and place binaries in the local folder:

```bash
# Places binaries to node_modules/playwright-core/.local-browsers
PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install
```

`PLAYWRIGHT_BROWSERS_PATH` does not change installation path for Google Chrome and Microsoft Edge.

### Skip browser downloads

In certain cases, it is desired to avoid browser downloads altogether because
browser binaries are managed separately.

This can be done by setting `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` variable before installation.

```bash
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 mvn test
```

### Stale browser removal

Playwright keeps track of the clients that use its browsers. When there are no more clients that require a particular version of the browser, that version is deleted from the system. That way you can safely use Playwright instances of different versions and at the same time, you don't waste disk space for the browsers that are no longer in use.

To opt-out from the unused browser removal, you can set the `PLAYWRIGHT_SKIP_BROWSER_GC=1` environment variable, or pass the `--no-remove` option to the install command:

```bash
npx playwright install --no-remove
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install --no-remove"
```

```bash
playwright install --no-remove
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install --no-remove
```

### List all installed browsers:

Prints list of browsers from all playwright installations on the machine.

```bash
npx playwright install --list
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="install --list"
```

```bash
playwright install --list
```

```bash
pwsh bin/Debug/netX/playwright.ps1 install --list
```

### Uninstall browsers

This will remove the browsers (chromium, firefox, webkit) of the current Playwright installation:

```bash
npx playwright uninstall
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="uninstall"
```

```bash
playwright uninstall
```

```bash
pwsh bin/Debug/netX/playwright.ps1 uninstall
```

To remove browsers of other Playwright installations as well, pass `--all` flag:

```bash
npx playwright uninstall --all
```

```bash
mvn exec:java -e -D exec.mainClass=com.microsoft.playwright.CLI -D exec.args="uninstall --all"
```

```bash
playwright uninstall --all
```

```bash
pwsh bin/Debug/netX/playwright.ps1 uninstall --all
```
