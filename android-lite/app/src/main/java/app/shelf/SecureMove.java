package app.shelf;

import android.net.Uri;
import android.webkit.CookieManager;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Moving to the server's secure (https) address (see src/shelf/secure.py and the native app's
 * SecureMove.kt, which follow the same rules).
 *
 * On plain http from the internet, passwords and music travel in the clear. When the server has
 * a secure address, the app moves there by itself, taking its sign-in (the session cookie) along.
 * At home (a private address) nothing changes.
 */
final class SecureMove {
    private SecureMove() {}

    private static final String[] PRIVATE_SUFFIXES = {".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net"};
    private static final Pattern V4 = Pattern.compile("^(\\d+)\\.(\\d+)\\.(\\d+)\\.(\\d+)$");
    private static final String COOKIE = "shelf_session";
    private static final int YEAR = 60 * 60 * 24 * 365;

    /** At home or on the tailnet: loopback, LAN, Tailscale's 100.64/10, bare names, .local and such. */
    static boolean isPrivate(String host) {
        String h = host.toLowerCase().replaceAll("^\\[|\\]$", "").replaceAll("\\.$", "");
        Matcher m = V4.matcher(h);
        if (m.matches()) {
            int a = Integer.parseInt(m.group(1)), b = Integer.parseInt(m.group(2));
            return a == 10 || a == 127 || a == 0 || (a == 172 && b >= 16 && b <= 31) || (a == 192 && b == 168)
                || (a == 169 && b == 254) || (a == 100 && b >= 64 && b <= 127);
        }
        if (h.contains(":")) return h.equals("::1") || h.startsWith("fc") || h.startsWith("fd") || h.matches("^fe[89ab].*");
        if (h.equals("localhost") || !h.contains(".")) return true;
        for (String s : PRIVATE_SUFFIXES) if (h.endsWith(s)) return true;
        return false;
    }

    /** Whether it's worth asking the server: plain http to an address on the internet. */
    static boolean worthAsking(String server) {
        Uri u = Uri.parse(server);
        return "http".equals(u.getScheme()) && u.getHost() != null && !isPrivate(u.getHost());
    }

    /** The secure address to move to, checked to be this server; null to stay. Network: not on the main thread. */
    static String target(String server) {
        try {
            String to = new JSONObject(get(server + "/api/session")).optString("secureUrl", "").replaceAll("/+$", "");
            if (!to.startsWith("https://")) return null;
            if (Uri.parse(to).getHost() == null || Uri.parse(to).getHost().equals(Uri.parse(server).getHost())) return null;
            if (!"shelf".equals(new JSONObject(get(to + "/api/ping")).optString("app"))) return null;
            return to;
        } catch (Exception e) {
            return null;
        }
    }

    /** The sign-in, carried to the new address. */
    static void carrySignIn(String from, String to) {
        CookieManager cm = CookieManager.getInstance();
        String all = cm.getCookie(from);
        if (all == null) return;
        for (String part : all.split(";")) {
            String p = part.trim();
            if (p.startsWith(COOKIE + "=")) {
                cm.setCookie(to, p + "; Path=/; Max-Age=" + YEAR + "; Secure; HttpOnly");
                cm.flush();
                return;
            }
        }
    }

    private static String get(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(7000);
        c.setReadTimeout(10000);
        try (InputStream in = c.getInputStream()) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
            return out.toString("UTF-8");
        } finally {
            c.disconnect();
        }
    }
}
