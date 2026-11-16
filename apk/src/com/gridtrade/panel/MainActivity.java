package com.gridtrade.panel;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;
import org.json.JSONTokener;

public class MainActivity extends Activity {
    private static final String TAG = "Gridtrade";
    private static final String PREFS = "gridtrade";
    private static final String DEFAULT_SERVER = "http://10.0.2.2:8000";

    private static final int MATCH_PARENT = ViewGroup.LayoutParams.MATCH_PARENT;
    private static final int WRAP_CONTENT = ViewGroup.LayoutParams.WRAP_CONTENT;

    private static final int BG = Color.rgb(11, 14, 17);
    private static final int SURFACE = Color.rgb(24, 26, 32);
    private static final int LINE = Color.rgb(43, 49, 57);
    private static final int INK = Color.rgb(234, 236, 239);
    private static final int MUTED = Color.rgb(132, 142, 156);
    private static final int FAINT = Color.rgb(94, 102, 115);
    private static final int ACCENT = Color.rgb(252, 213, 53);
    private static final int DARK = Color.rgb(11, 14, 17);

    private SharedPreferences prefs;
    private FrameLayout root;
    private FrameLayout panel;
    private WebView webView;
    private ProgressBar progress;
    private FrameLayout errorPanel;
    private TextView errorMessage;
    private EditText serverInput;
    private EditText tokenInput;
    private String server = "";
    private String injectedToken = "";
    private boolean pageFailed = false;
    private boolean tokenPushed = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        Window window = getWindow();
        window.setStatusBarColor(BG);
        window.setNavigationBarColor(BG);
        window.getDecorView().setSystemUiVisibility(0);
        root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        root.setFitsSystemWindows(true);
        setContentView(root);
        String savedServer = prefs.getString("server", "").trim();
        if (savedServer.isEmpty()) {
            showSetup();
        } else {
            showPanel(savedServer, prefs.getString("token", "").trim());
        }
    }

    private void showSetup() {
        destroyPanel();
        root.removeAllViews();
        String savedServer = prefs.getString("server", "").trim();
        String savedToken = prefs.getString("token", "").trim();

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);

        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(24), dp(36), dp(24), dp(32));
        scroll.addView(body, new ScrollView.LayoutParams(MATCH_PARENT, WRAP_CONTENT));

        TextView brand = text("GRIDTRADE", 11, ACCENT, Typeface.BOLD);
        brand.setLetterSpacing(0.18f);
        add(body, brand, 0, 0);

        add(body, text("量化研究终端", 25, INK, Typeface.BOLD), 0, 10);

        TextView blurb = text(
                "连接你的 gridtrade 服务端，运行回放、参数扫描与前向滚动研究。"
                        + "仅支持研究与模拟盘 \u2014 实盘交易在 API 层保持锁定。",
                12.5f, MUTED, Typeface.NORMAL);
        blurb.setLineSpacing(0, 1.35f);
        add(body, blurb, 0, 12);

        add(body, label("服务器地址"), 0, 30);

        serverInput = field(savedServer.isEmpty() ? DEFAULT_SERVER : savedServer, false);
        serverInput.setHint(DEFAULT_SERVER);
        add(body, serverInput, 48, 8);

        add(body, label("访问令牌"), 0, 18);

        tokenInput = field(savedToken, true);
        tokenInput.setHint("粘贴 var/token 中的值");
        tokenInput.setImeOptions(EditorInfo.IME_ACTION_GO);
        add(body, tokenInput, 48, 8);

        add(body, text("令牌位于服务端的 var/token，仅保存在本设备。",
                10.5f, FAINT, Typeface.NORMAL), 0, 8);

        Button connect = new Button(this);
        connect.setText("打开面板");
        connect.setAllCaps(false);
        connect.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14.5f);
        connect.setTextColor(DARK);
        connect.setTypeface(Typeface.DEFAULT_BOLD);
        connect.setBackground(rounded(ACCENT, 0, 12));
        connect.setOnClickListener(v -> connect());
        add(body, connect, 50, 24);

        TextView tip = text(
                "\u2022 模拟器：10.0.2.2 可访问宿主机。\n"
                        + "\u2022 手机：使用局域网或 Tailscale 地址，建议走 HTTPS。\n"
                        + "\u2022 面板单独保存本设备的令牌，与网页端互不影响。",
                10.5f, FAINT, Typeface.NORMAL);
        tip.setLineSpacing(0, 1.45f);
        add(body, tip, 0, 16);

        tokenInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_GO) {
                connect();
                return true;
            }
            return false;
        });

        root.addView(scroll, match());
        if (savedToken.isEmpty()) tokenInput.requestFocus();
    }

    private void connect() {
        String address = normalize(serverInput.getText().toString());
        if (address.isEmpty()) {
            toast("请输入服务器地址");
            return;
        }
        String token = tokenInput.getText().toString().trim();
        prefs.edit().putString("server", address).putString("token", token).apply();
        hideKeyboard();
        showPanel(address, token);
    }

    private void showPanel(String address, String token) {
        destroyPanel();
        root.removeAllViews();
        server = address;
        injectedToken = token;
        tokenPushed = false;
        pageFailed = false;

        panel = new FrameLayout(this);
        panel.setBackgroundColor(BG);
        root.addView(panel, match());

        webView = new WebView(this);
        webView.setBackgroundColor(BG);
        configureWebView();
        panel.addView(webView, match());

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setProgress(0);
        progress.setProgressTintList(ColorStateList.valueOf(ACCENT));
        FrameLayout.LayoutParams progressParams = new FrameLayout.LayoutParams(MATCH_PARENT, dp(2));
        progressParams.gravity = Gravity.TOP;
        panel.addView(progress, progressParams);

        buildErrorPanel();
        webView.loadUrl(server);
    }

    private void buildErrorPanel() {
        errorPanel = new FrameLayout(this);
        errorPanel.setBackgroundColor(BG);
        errorPanel.setVisibility(View.GONE);

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        box.setPadding(dp(28), dp(24), dp(28), dp(24));
        box.setBackground(rounded(SURFACE, LINE, 14));
        FrameLayout.LayoutParams boxParams = new FrameLayout.LayoutParams(dp(300), WRAP_CONTENT);
        boxParams.gravity = Gravity.CENTER;
        errorPanel.addView(box, boxParams);

        TextView title = text("无法连接服务器", 16, INK, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        box.addView(title);

        errorMessage = text("", 11.5f, MUTED, Typeface.NORMAL);
        errorMessage.setGravity(Gravity.CENTER);
        errorMessage.setLineSpacing(0, 1.3f);
        LinearLayout.LayoutParams messageParams = new LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT);
        messageParams.topMargin = dp(8);
        box.addView(errorMessage, messageParams);

        Button retry = smallButton("重试", DARK, ACCENT);
        retry.setOnClickListener(v -> {
            errorPanel.setVisibility(View.GONE);
            webView.reload();
        });
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(MATCH_PARENT, dp(44));
        retryParams.topMargin = dp(18);
        box.addView(retry, retryParams);

        Button settings = smallButton("服务器与令牌", INK, Color.TRANSPARENT);
        settings.setBackground(rounded(Color.TRANSPARENT, LINE, 10));
        settings.setOnClickListener(v -> showSetup());
        LinearLayout.LayoutParams settingsParams = new LinearLayout.LayoutParams(MATCH_PARENT, dp(44));
        settingsParams.topMargin = dp(8);
        box.addView(settings, settingsParams);

        panel.addView(errorPanel, match());
    }

    private void configureWebView() {
        WebView.setWebContentsDebuggingEnabled(true);
        WebSettings settings = webView.getSettings();
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setUserAgentString(settings.getUserAgentString() + " GridtradeShell/0.1");

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, false);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                String host = target.getHost();
                String baseHost = Uri.parse(server).getHost();
                if (host != null && baseHost != null && host.equalsIgnoreCase(baseHost)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, target));
                } catch (Exception ignored) {
                }
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                pageFailed = false;
                hideError();
                if (progress != null) {
                    progress.setProgress(5);
                    progress.setVisibility(View.VISIBLE);
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!pageFailed && progress != null) progress.setVisibility(View.GONE);
                syncToken();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (!request.isForMainFrame()) return;
                pageFailed = true;
                if (progress != null) progress.setVisibility(View.GONE);
                CharSequence description = error.getDescription();
                showError(description == null ? null : description.toString());
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (progress == null) return;
                progress.setProgress(newProgress);
                if (newProgress >= 100 && !pageFailed) progress.setVisibility(View.GONE);
            }

            @Override
            public boolean onConsoleMessage(android.webkit.ConsoleMessage message) {
                Log.d(TAG, "web " + message.lineNumber() + ": " + message.message());
                return true;
            }
        });
    }

    private void syncToken() {
        if (webView == null) return;
        webView.evaluateJavascript(
                "(function(){try{return localStorage.getItem('gridtrade.token')||'';}catch(e){return '';}})()",
                value -> {
                    String current = decode(value);
                    if (!injectedToken.isEmpty() && !injectedToken.equals(current) && !tokenPushed) {
                        tokenPushed = true;
                        String js = "try{localStorage.setItem('gridtrade.token', "
                                + JSONObject.quote(injectedToken) + ");}catch(e){}";
                        webView.evaluateJavascript(js, null);
                        webView.reload();
                    } else if (!current.isEmpty()) {
                        String saved = prefs.getString("token", "");
                        if (!current.equals(saved)) prefs.edit().putString("token", current).apply();
                    }
                });
    }

    private String decode(String value) {
        if (value == null || "null".equals(value)) return "";
        try {
            Object parsed = new JSONTokener(value).nextValue();
            return parsed instanceof String ? (String) parsed : "";
        } catch (Exception error) {
            return "";
        }
    }

    private void showError(String message) {
        if (errorMessage != null) {
            errorMessage.setText(message == null || message.trim().isEmpty()
                    ? "请检查地址、API 进程与网络后重试。"
                    : message);
        }
        if (errorPanel != null) errorPanel.setVisibility(View.VISIBLE);
    }

    private void hideError() {
        if (errorPanel != null) errorPanel.setVisibility(View.GONE);
    }

    private void destroyPanel() {
        if (panel != null) {
            root.removeView(panel);
            panel = null;
        }
        if (webView != null) {
            webView.stopLoading();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        progress = null;
        errorPanel = null;
        errorMessage = null;
    }

    private void signOut() {
        prefs.edit().remove("token").apply();
        CookieManager.getInstance().removeAllCookies(null);
        WebView current = webView;
        if (current != null) {
            current.evaluateJavascript(
                    "try{localStorage.removeItem('gridtrade.token');}catch(e){}",
                    value -> showSetup());
        } else {
            showSetup();
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        if (webView != null) {
            showPanelMenu();
            return;
        }
        super.onBackPressed();
    }

    private void showPanelMenu() {
        new AlertDialog.Builder(this)
                .setTitle("面板")
                .setItems(new String[]{"重新加载", "服务器与令牌", "退出登录", "退出应用"},
                        (dialog, which) -> {
                            if (which == 0) {
                                webView.reload();
                            } else if (which == 1) {
                                showSetup();
                            } else if (which == 2) {
                                signOut();
                            } else {
                                finish();
                            }
                        })
                .setNegativeButton("取消", null)
                .show();
    }

    @Override
    protected void onPause() {
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onDestroy() {
        destroyPanel();
        super.onDestroy();
    }

    private String normalize(String raw) {
        String value = raw.trim();
        if (value.isEmpty()) return "";
        if (!value.matches("(?i)^https?://.*")) value = "http://" + value;
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        return value;
    }

    private EditText field(String value, boolean secret) {
        EditText edit = new EditText(this);
        edit.setText(value);
        edit.setSingleLine(true);
        edit.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        edit.setTextColor(INK);
        edit.setHintTextColor(FAINT);
        edit.setTypeface(Typeface.MONOSPACE);
        edit.setBackground(rounded(SURFACE, LINE, 10));
        edit.setPadding(dp(12), 0, dp(12), 0);
        edit.setInputType(secret
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        return edit;
    }

    private TextView label(String value) {
        TextView view = text(value, 10, FAINT, Typeface.BOLD);
        view.setLetterSpacing(0.12f);
        return view;
    }

    private TextView text(String value, float sizeSp, int color, int style) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp);
        view.setTextColor(color);
        view.setTypeface(Typeface.create(Typeface.SANS_SERIF, style));
        return view;
    }

    private Button smallButton(String label, int textColor, int fill) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f);
        button.setTextColor(textColor);
        button.setBackground(rounded(fill, 0, 10));
        button.setPadding(dp(12), 0, dp(12), 0);
        return button;
    }

    private void add(LinearLayout parent, View view, int heightDp, int topDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                MATCH_PARENT, heightDp == 0 ? WRAP_CONTENT : dp(heightDp));
        params.topMargin = dp(topDp);
        parent.addView(view, params);
    }

    private ViewGroup.LayoutParams match() {
        return new FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT);
    }

    private GradientDrawable rounded(int fill, int stroke, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radiusDp));
        if (stroke != 0) drawable.setStroke(dp(1), stroke);
        return drawable;
    }

    private int dp(int value) {
        return Math.round(getResources().getDisplayMetrics().density * value);
    }

    private void hideKeyboard() {
        View focus = getCurrentFocus();
        InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (focus != null && keyboard != null) {
            keyboard.hideSoftInputFromWindow(focus.getWindowToken(), 0);
        }
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }
}
