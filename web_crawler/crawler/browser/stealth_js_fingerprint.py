STEALTH_JS_FINGERPRINT = """
                    // 8. WebGL Vendor & Renderer Spoofing (Dynamic matching)
                    if (win.WebGLRenderingContext) {{
                        const realGetParameter = win.WebGLRenderingContext.prototype.getParameter;
                        win.WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                            if (parameter === 37445 || parameter === 0x9245) return profile.webgl_vendor;
                            if (parameter === 37446 || parameter === 0x9246) return profile.webgl_renderer;
                            return realGetParameter.apply(this, arguments);
                        }};
                        makeNative(win.WebGLRenderingContext.prototype.getParameter, 'getParameter');

                        // WebGL Supported Extensions
                        win.WebGLRenderingContext.prototype.getSupportedExtensions = function() {{
                            return [
                                "ANGLE_instanced_arrays", "EXT_blend_minmax", "EXT_color_buffer_half_float",
                                "EXT_float_blend", "EXT_frag_depth", "EXT_shader_texture_lod", 
                                "EXT_sRGB", "EXT_texture_compression_bptc", "EXT_texture_filter_anisotropic",
                                "OES_element_index_uint", "OES_fbo_render_mipmap", "OES_standard_derivatives",
                                "OES_texture_float", "OES_texture_float_linear", "OES_texture_half_float",
                                "OES_texture_half_float_linear", "OES_vertex_array_object", "WEBGL_color_buffer_float",
                                "WEBGL_compressed_texture_s3tc", "WEBGL_compressed_texture_s3tc_srgb", 
                                "WEBGL_debug_renderer_info", "WEBGL_debug_shaders", "WEBGL_depth_texture",
                                "WEBGL_draw_buffers", "WEBGL_lose_context"
                            ];
                        }};
                        makeNative(win.WebGLRenderingContext.prototype.getSupportedExtensions, 'getSupportedExtensions');

                        // WebGL Context Attributes
                        win.WebGLRenderingContext.prototype.getContextAttributes = function() {{
                            return {{
                                alpha: true,
                                antialias: true,
                                depth: true,
                                failIfMajorPerformanceCaveat: false,
                                powerPreference: "high-performance",
                                premultipliedAlpha: true,
                                preserveDrawingBuffer: false,
                                stencil: false,
                                desynchronized: false
                            }};
                        }};
                        makeNative(win.WebGLRenderingContext.prototype.getContextAttributes, 'getContextAttributes');

                        // WebGL Shader Precision Formats
                        win.WebGLRenderingContext.prototype.getShaderPrecisionFormat = function(shaderType, precisionType) {{
                            return {{
                                rangeMin: 127,
                                rangeMax: 127,
                                precision: 23
                            }};
                        }};
                        makeNative(win.WebGLRenderingContext.prototype.getShaderPrecisionFormat, 'getShaderPrecisionFormat');
                    }}

                    if (win.WebGL2RenderingContext) {{
                        const realGetParameter2 = win.WebGL2RenderingContext.prototype.getParameter;
                        win.WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
                            if (parameter === 37445 || parameter === 0x9245) return profile.webgl_vendor;
                            if (parameter === 37446 || parameter === 0x9246) return profile.webgl_renderer;
                            return realGetParameter2.apply(this, arguments);
                        }};
                        makeNative(win.WebGL2RenderingContext.prototype.getParameter, 'getParameter');

                        // WebGL2 Supported Extensions
                        win.WebGL2RenderingContext.prototype.getSupportedExtensions = function() {{
                            return [
                                "EXT_color_buffer_float", "EXT_color_buffer_half_float", "EXT_float_blend",
                                "EXT_texture_compression_bptc", "EXT_texture_filter_anisotropic",
                                "OES_texture_float_linear", "WEBGL_compressed_texture_s3tc", 
                                "WEBGL_compressed_texture_s3tc_srgb", "WEBGL_debug_renderer_info", 
                                "WEBGL_debug_shaders", "WEBGL_lose_context"
                            ];
                        }};
                        makeNative(win.WebGL2RenderingContext.prototype.getSupportedExtensions, 'getSupportedExtensions');

                        // WebGL2 Context Attributes & Precision Inherits
                        win.WebGL2RenderingContext.prototype.getContextAttributes = win.WebGLRenderingContext.prototype.getContextAttributes;
                        win.WebGL2RenderingContext.prototype.getShaderPrecisionFormat = win.WebGLRenderingContext.prototype.getShaderPrecisionFormat;
                    }}

                    // 9. WebRTC IP Leak Prevention (Sanitize candidates)
                    const RealRTCPeerConnection = win.RTCPeerConnection || win.webkitRTCPeerConnection || win.mozRTCPeerConnection;
                    if (RealRTCPeerConnection) {{
                        const FakeRTCPeerConnection = function(config) {{
                            const pc = new RealRTCPeerConnection(config);
                            const realCreateOffer = pc.createOffer;
                            pc.createOffer = function() {{
                                return realCreateOffer.apply(this, arguments).then(offer => {{
                                    offer.sdp = offer.sdp.replace(/(\\\\r\\\\n|\\\\n)a=candidate:[^\\\\r\\\\n]*\\\\b(192\\\\.168\\\\.[0-9.]+|10\\\\.[0-9.]+|172\\\\.(1[6-9]|2[0-9]|3[0-1])\\\\.[0-9.]+|[0-9a-fA-F]{{1,4}}(::?[0-9a-fA-F]{{1,4}}){{1,7}})\\\\b[^\\\\r\\\\n]*/g, '');
                                    return offer;
                                }});
                            }};
                            return pc;
                        }};
                        FakeRTCPeerConnection.prototype = RealRTCPeerConnection.prototype;
                        win.RTCPeerConnection = FakeRTCPeerConnection;
                        if (win.webkitRTCPeerConnection) win.webkitRTCPeerConnection = FakeRTCPeerConnection;
                        if (win.mozRTCPeerConnection) win.mozRTCPeerConnection = FakeRTCPeerConnection;
                    }}

                    // 10. Screen, Window, and Viewport Property Spoofing
                    Object.defineProperty(win.screen, 'width', {{ get: () => 1920, configurable: true }});
                    Object.defineProperty(win.screen, 'height', {{ get: () => 1080, configurable: true }});
                    Object.defineProperty(win.screen, 'availWidth', {{ get: () => 1920, configurable: true }});
                    Object.defineProperty(win.screen, 'availHeight', {{ get: () => 1040, configurable: true }});
                    Object.defineProperty(win, 'outerWidth', {{ get: () => 1920, configurable: true }});
                    Object.defineProperty(win, 'outerHeight', {{ get: () => 1080, configurable: true }});
                    Object.defineProperty(win, 'innerWidth', {{ get: () => 1920, configurable: true }});
                    Object.defineProperty(win, 'innerHeight', {{ get: () => 1080, configurable: true }});

                    // 11. Concurrency and Memory Info
                    Object.defineProperty(win.navigator, 'hardwareConcurrency', {{ get: () => profile.concurrency, configurable: true }});
                    Object.defineProperty(win.navigator, 'deviceMemory', {{ get: () => profile.device_memory, configurable: true }});
                    Object.defineProperty(win.navigator, 'platform', {{ get: () => profile.platform, configurable: true }});
                    if (profile.oscpu) {{
                        Object.defineProperty(win.navigator, 'oscpu', {{ get: () => profile.oscpu, configurable: true }});
                    }}

                    // 12. AudioContext & Speech synthesis Mocks
                    const RealAudioContext = win.AudioContext || win.webkitAudioContext;
                    if (RealAudioContext) {{
                        const FakeAudioContext = function() {{
                            const ctx = new RealAudioContext();
                            Object.defineProperty(ctx, 'sampleRate', {{ get: () => 44100, configurable: true }});
                            Object.defineProperty(ctx, 'outputLatency', {{ get: () => 0.01, configurable: true }});
                            if (ctx.destination) {{
                                Object.defineProperty(ctx.destination, 'maxChannelCount', {{ get: () => 2, configurable: true }});
                            }}
                            return ctx;
                        }};
                        FakeAudioContext.prototype = RealAudioContext.prototype;
                        win.AudioContext = FakeAudioContext;
                        if (win.webkitAudioContext) win.webkitAudioContext = FakeAudioContext;
                    }}

                    // Audio Buffer Noise Injection
                    const RealOfflineAudioContext = win.OfflineAudioContext || win.webkitOfflineAudioContext;
                    if (RealOfflineAudioContext) {{
                        const originalStartRendering = RealOfflineAudioContext.prototype.startRendering;
                        RealOfflineAudioContext.prototype.startRendering = function() {{
                            return originalStartRendering.apply(this, arguments).then(buffer => {{
                                try {{
                                    const seed = profile.audio_seed;
                                    const channels = buffer.numberOfChannels;
                                    for (let channel = 0; channel < channels; channel++) {{
                                        const channelData = buffer.getChannelData(channel);
                                        const step = Math.max(1, Math.floor(channelData.length / 500));
                                        for (let i = 0; i < channelData.length; i += step) {{
                                            channelData[i] += (seed % 100) * 1e-9;
                                        }}
                                    }}
                                }} catch (e) {{}}
                                return buffer;
                            }});
                        }};
                        makeNative(RealOfflineAudioContext.prototype.startRendering, 'startRendering');
                    }}
                    
                    if (win.AudioBuffer) {{
                        const originalGetChannelData = win.AudioBuffer.prototype.getChannelData;
                        win.AudioBuffer.prototype.getChannelData = function(channel) {{
                            const data = originalGetChannelData.apply(this, arguments);
                            try {{
                                const seed = profile.audio_seed;
                                const step = Math.max(1, Math.floor(data.length / 500));
                                for (let i = 0; i < data.length; i += step) {{
                                    data[i] += (seed % 100) * 1e-9;
                                }}
                            }} catch (e) {{}}
                            return data;
                        }};
                        makeNative(win.AudioBuffer.prototype.getChannelData, 'getChannelData');
                    }}

                    if (win.speechSynthesis) {{
                        win.speechSynthesis.getVoices = function() {{
                            return profile.voices;
                        }};
                        makeNative(win.speechSynthesis.getVoices, 'getVoices');
                    }}

                    // 13. Battery API Spoofing
                    if (win.navigator.getBattery) {{
                        win.navigator.getBattery = function() {{
                            return Promise.resolve({{
                                charging: true,
                                chargingTime: 0,
                                dischargingTime: Infinity,
                                level: 1.0,
                                onchargingchange: null,
                                onchargingtimechange: null,
                                ondischargingtimechange: null,
                                onlevelchange: null
                            }});
                        }};
                        makeNative(win.navigator.getBattery, 'getBattery');
                    }}

                    // 14. Microphones, Webcams, Speakers Info Mocking
                    if (win.navigator.mediaDevices && win.navigator.mediaDevices.enumerateDevices) {{
                        win.navigator.mediaDevices.enumerateDevices = function() {{
                            return Promise.resolve([
                                {{ deviceId: "default", kind: "audioinput", label: "Default Audio Input", groupId: "group1" }},
                                {{ deviceId: "default", kind: "videoinput", label: "Integrated Camera", groupId: "group2" }},
                                {{ deviceId: "default", kind: "audiooutput", label: "Default Audio Output", groupId: "group1" }}
                            ]);
                        }};
                        makeNative(win.navigator.mediaDevices.enumerateDevices, 'enumerateDevices');
                    }}

                    // 15. User-Agent Client Hints (userAgentData) matching target Chromium major version dynamically
                    if (win.navigator.userAgent) {{
                        const ua = win.navigator.userAgent;
                        const chromeMatch = ua.match(/Chrome\\\\/(\\\\d+)\\\\.(\\\\d+)\\\\.(\\\\d+)\\\\.(\\\\d+)/);
                        const chromeVersion = chromeMatch ? chromeMatch[1] : '133';
                        const chromeFullVersion = chromeMatch ? chromeMatch[0].split('/')[1] : '133.0.0.0';
                        
                        const mockUserAgentData = {{
                            brands: [
                                {{ brand: 'Not(A:Brand', version: '99' }},
                                {{ brand: 'Google Chrome', version: chromeVersion }},
                                {{ brand: 'Chromium', version: chromeVersion }}
                            ],
                            mobile: false,
                            platform: 'Windows',
                            getHighEntropyValues: function(hints) {{
                                return Promise.resolve({{
                                    platform: 'Windows',
                                    platformVersion: '10.0.0',
                                    architecture: 'x86',
                                    model: '',
                                    uaFullVersion: chromeFullVersion,
                                    fullVersionList: [
                                        {{ brand: 'Not(A:Brand', version: '99.0.0.0' }},
                                        {{ brand: 'Google Chrome', version: chromeFullVersion }},
                                        {{ brand: 'Chromium', version: chromeFullVersion }}
                                    ]
                                }});
                            }}
                        }};
                        makeNative(mockUserAgentData.getHighEntropyValues, 'getHighEntropyValues');
                        
                        Object.defineProperty(win.navigator, 'userAgentData', {{
                            get: () => mockUserAgentData,
                            configurable: true
                        }});
                    }}

                    // 16. Canvas Fingerprint Spoofing (Deterministic micro-noise injection)
                    if (win.HTMLCanvasElement && win.CanvasRenderingContext2D) {{
                        const originalGetImageData = win.CanvasRenderingContext2D.prototype.getImageData;
                        win.CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {{
                            const imageData = originalGetImageData.apply(this, arguments);
                            const data = imageData.data;
                            const seed = profile.canvas_seed;
                            for (let i = 0; i < data.length; i += 4) {{
                                const val = Math.sin(i + seed);
                                if (data[i] > 0 && data[i] < 255) {{
                                    data[i] += val > 0.5 ? 1 : (val < -0.5 ? -1 : 0);
                                }}
                                if (data[i+1] > 0 && data[i+1] < 255) {{
                                    data[i+1] += val > 0.1 ? 1 : (val < -0.1 ? -1 : 0);
                                }}
                                if (data[i+2] > 0 && data[i+2] < 255) {{
                                    data[i+2] += val > 0.3 ? 1 : (val < -0.3 ? -1 : 0);
                                }}
                            }}
                            return imageData;
                        }};
                        makeNative(win.CanvasRenderingContext2D.prototype.getImageData, 'getImageData');

                        const originalToDataURL = win.HTMLCanvasElement.prototype.toDataURL;
                        win.HTMLCanvasElement.prototype.toDataURL = function() {{
                            const ctx = this.getContext('2d');
                            if (ctx) {{
                                try {{
                                    const width = this.width;
                                    const height = this.height;
                                    if (width > 0 && height > 0) {{
                                        const imgData = ctx.getImageData(0, 0, 1, 1);
                                        const seed = profile.canvas_seed;
                                        imgData.data[0] = (imgData.data[0] + (seed % 3) + 1) % 256;
                                        ctx.putImageData(imgData, 0, 0);
                                    }}
                                }} catch (e) {{}}
                            }}
                            return originalToDataURL.apply(this, arguments);
                        }};
                        makeNative(win.HTMLCanvasElement.prototype.toDataURL, 'toDataURL');
                    }}

                    // Anti-Font Metrics Fingerprinting (Deterministic text measure and layout offsets)
                    if (win.CanvasRenderingContext2D) {{
                        const originalMeasureText = win.CanvasRenderingContext2D.prototype.measureText;
                        win.CanvasRenderingContext2D.prototype.measureText = function(text) {{
                            const result = originalMeasureText.apply(this, arguments);
                            const seed = profile.font_spacing_seed;
                            const offset = (Math.sin(text.length + seed) * 0.0001);
                            return {{
                                width: result.width + offset,
                                actualBoundingBoxLeft: result.actualBoundingBoxLeft,
                                actualBoundingBoxRight: result.actualBoundingBoxRight,
                                fontBoundingBoxAscent: result.fontBoundingBoxAscent,
                                fontBoundingBoxDescent: result.fontBoundingBoxDescent,
                                emHeightAscent: result.emHeightAscent,
                                emHeightDescent: result.emHeightDescent,
                                hangingBaseline: result.hangingBaseline,
                                alphabeticBaseline: result.alphabeticBaseline,
                                ideographicBaseline: result.ideographicBaseline
                            }};
                        }};
                        makeNative(win.CanvasRenderingContext2D.prototype.measureText, 'measureText');
                    }}

                    const originalOffsetWidth = Object.getOwnPropertyDescriptor(win.HTMLElement.prototype, 'offsetWidth').get;
                    const originalOffsetHeight = Object.getOwnPropertyDescriptor(win.HTMLElement.prototype, 'offsetHeight').get;
                    Object.defineProperty(win.HTMLElement.prototype, 'offsetWidth', {{
                        get: function() {{
                            const val = originalOffsetWidth.call(this);
                            const seed = profile.font_spacing_seed;
                            return val > 0 ? val + (Math.sin(val + seed) * 0.01) : val;
                        }},
                        configurable: true
                    }});
                    Object.defineProperty(win.HTMLElement.prototype, 'offsetHeight', {{
                        get: function() {{
                            const val = originalOffsetHeight.call(this);
                            const seed = profile.font_spacing_seed;
                            return val > 0 ? val + (Math.cos(val + seed) * 0.01) : val;
                        }},
                        configurable: true
                    }});

                    // 17. Dynamic Iframe Prototype Hooking
                    if (win.HTMLIFrameElement) {{
                        const originalIframeContentWindow = Object.getOwnPropertyDescriptor(win.HTMLIFrameElement.prototype, 'contentWindow').get;
                        Object.defineProperty(win.HTMLIFrameElement.prototype, 'contentWindow', {{
                            get: function() {{
                                const iframeWin = originalIframeContentWindow.call(this);
                                if (iframeWin) {{
                                    try {{
                                        applyStealthToWindow(iframeWin);
                                    }} catch (e) {{}}
                                }}
                                return iframeWin;
                            }},
                            configurable: true,
                            enumerable: true
                        }});
                        makeNative(Object.getOwnPropertyDescriptor(win.HTMLIFrameElement.prototype, 'contentWindow').get, 'get contentWindow');
                    }}
                }};

                // Clean automation properties first (window and document level)
                const cleanProps = (obj) => {{
                    if (!obj) return;
                    for (const prop in obj) {{
                        try {{
                            if (prop.startsWith('cdc_') || prop.startsWith('__playwright') || prop.startsWith('__pw')) {{
                                delete obj[prop];
                            }}
                        }} catch (e) {{}}
                    }}
                }};
                cleanProps(window);
                cleanProps(document);

                // Inject to the main window
                applyStealthToWindow(window);
"""
