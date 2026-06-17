STEALTH_JS_CORE = """
                // Bulletproof Global Function.prototype.toString Hook to match native signatures
                const originalToString = Function.prototype.toString;
                const spoofedFunctions = new Map();

                Function.prototype.toString = function() {{
                    if (spoofedFunctions.has(this)) {{
                        return spoofedFunctions.get(this);
                    }}
                    return originalToString.call(this);
                }};
                spoofedFunctions.set(Function.prototype.toString, 'function toString() {{ [native code] }}');

                const makeNative = (func, name) => {{
                    if (!func) return;
                    const funcName = name || func.name || '';
                    spoofedFunctions.set(func, `function ${{funcName}}() {{ [native code] }}`);
                    try {{
                        Object.defineProperty(func, 'name', {{ value: funcName, configurable: true }});
                    }} catch (e) {{}}
                }};

                const profile = {profile_js};

                const applyStealthToWindow = (win) => {{
                    if (win.__stealth_applied) return;
                    win.__stealth_applied = true;

                    // 1. Mask navigator.webdriver properly
                    if (win.Navigator) {{
                        const proto = win.Navigator.prototype;
                        try {{
                            Object.defineProperty(proto, 'webdriver', {{
                                get: function() {{ return false; }},
                                configurable: true,
                                enumerable: true
                            }});
                            const webdriverGetter = Object.getOwnPropertyDescriptor(proto, 'webdriver').get;
                            makeNative(webdriverGetter, 'get webdriver');
                        }} catch (e) {{
                            Object.defineProperty(win.navigator, 'webdriver', {{
                                get: () => false,
                                configurable: true,
                                enumerable: true
                            }});
                            const webdriverGetter = Object.getOwnPropertyDescriptor(win.navigator, 'webdriver').get;
                            makeNative(webdriverGetter, 'get webdriver');
                        }}
                    }} else {{
                        Object.defineProperty(win.navigator, 'webdriver', {{
                            get: () => false,
                            configurable: true,
                            enumerable: true
                        }});
                        const webdriverGetter = Object.getOwnPropertyDescriptor(win.navigator, 'webdriver').get;
                        makeNative(webdriverGetter, 'get webdriver');
                    }}

                    // 2. Fake win.chrome
                    win.chrome = {{
                        app: {{
                            isInstalled: false,
                            InstallState: {{
                                DISABLED: 'disabled',
                                INSTALLED: 'installed',
                                NOT_INSTALLED: 'not_installed'
                            }},
                            RunningState: {{
                                CANNOT_RUN: 'cannot_run',
                                READY_TO_RUN: 'ready_to_run',
                                RUNNING: 'running'
                            }}
                        }},
                        runtime: {{
                            OnInstalledReason: {{
                                CHROME_UPDATE: 'chrome_update',
                                INSTALL: 'install',
                                SHARED_MODULE_UPDATE: 'shared_module_update',
                                UPDATE: 'update'
                            }},
                            OnRestartRequiredReason: {{
                                APP_UPDATE: 'app_update',
                                OS_UPDATE: 'os_update',
                                PERIODIC: 'periodic'
                            }},
                            PlatformArch: {{
                                ARM: 'arm',
                                ARM64: 'arm64',
                                MIPS: 'mips',
                                MIPS64: 'mips64',
                                X86_32: 'x86-32',
                                X86_64: 'x86-64'
                            }},
                            PlatformNaclArch: {{
                                ARM: 'arm',
                                MIPS: 'mips',
                                MIPS64: 'mips64',
                                X86_32: 'x86-32',
                                X86_64: 'x86-64'
                            }},
                            PlatformOs: {{
                                ANDROID: 'android',
                                CROS: 'cros',
                                LINUX: 'linux',
                                MAC: 'mac',
                                OPENBSD: 'openbsd',
                                WIN: 'win'
                            }},
                            RequestUpdateCheckStatus: {{
                                NO_UPDATE: 'no_update',
                                THROTTLED: 'throttled',
                                UPDATE_AVAILABLE: 'update_available'
                            }},
                            connect: function() {{}},
                            sendMessage: function() {{}}
                        }},
                        csi: function() {{}},
                        loadTimes: function() {{}}
                    }};
                    makeNative(win.chrome.runtime.connect, 'connect');
                    makeNative(win.chrome.runtime.sendMessage, 'sendMessage');
                    makeNative(win.chrome.csi, 'csi');
                    makeNative(win.chrome.loadTimes, 'loadTimes');

                    // 3. Real Desktop Plugins Mock (prototype compliant)
                    if (!win.navigator.plugins || win.navigator.plugins.length === 0) {{
                        const pluginArrayProto = win.PluginArray ? win.PluginArray.prototype : Object.prototype;
                        const mockPlugins = Object.create(pluginArrayProto);
                        const mockPluginsList = [
                            {{ name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
                            {{ name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
                            {{ name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }}
                        ];
                        
                        mockPluginsList.forEach((p, idx) => {{
                            const pluginProto = win.Plugin ? win.Plugin.prototype : Object.prototype;
                            const mockPlugin = Object.create(pluginProto);
                            Object.defineProperties(mockPlugin, {{
                                name: {{ get: () => p.name, configurable: true }},
                                filename: {{ get: () => p.filename, configurable: true }},
                                description: {{ get: () => p.description, configurable: true }},
                                length: {{ get: () => 0, configurable: true }}
                            }});
                            mockPlugins[idx] = mockPlugin;
                            mockPlugins[p.name] = mockPlugin;
                        }});
                        
                        Object.defineProperties(mockPlugins, {{
                            length: {{ get: () => mockPluginsList.length, configurable: true }},
                            item: {{ value: (index) => mockPlugins[index], configurable: true }},
                            namedItem: {{ value: (name) => mockPlugins[name], configurable: true }}
                        }});
                        makeNative(mockPlugins.item, 'item');
                        makeNative(mockPlugins.namedItem, 'namedItem');
                        
                        Object.defineProperty(win.navigator, 'plugins', {{
                            get: () => mockPlugins,
                            configurable: true
                        }});
                    }}

                    // 4. Touch points
                    Object.defineProperty(win.navigator, 'maxTouchPoints', {{
                        get: () => 0,
                        configurable: true
                    }});

                    // 5. Non-empty languages matching context locale
                    Object.defineProperty(win.navigator, 'languages', {{
                        get: () => {languages_js},
                        configurable: true
                    }});

                    // 6. Prevent Notification.permission from revealing headless
                    if (win.Notification) {{
                        Object.defineProperty(win.Notification, 'permission', {{
                            get: () => 'default',
                            configurable: true
                        }});
                    }}

                    // 7. Notification permission query mock (prototype compliant)
                    if (win.navigator.permissions && win.navigator.permissions.query) {{
                        const originalQuery = win.navigator.permissions.query;
                        win.navigator.permissions.query = function(parameters) {{
                            if (parameters && parameters.name === 'notifications') {{
                                return originalQuery.call(win.navigator.permissions, {{ name: 'geolocation' }}).then(status => {{
                                    const mockedStatus = Object.create(status);
                                    Object.defineProperty(mockedStatus, 'state', {{
                                        get: () => win.Notification.permission,
                                        configurable: true
                                    }});
                                    return mockedStatus;
                                }}).catch(() => {{
                                    return Promise.resolve({{
                                        state: win.Notification.permission,
                                        onchange: null
                                    }});
                                }});
                            }}
                            return originalQuery.call(win.navigator.permissions, parameters);
                        }};
                        makeNative(win.navigator.permissions.query, 'query');
                    }}
"""
