package app.shelf;

import android.content.Context;
import android.webkit.CookieManager;
import android.webkit.WebResourceResponse;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;

/**
 * A copy of the web app's files (the page, scripts, styles, fonts, icons), refreshed every
 * time they load, and used when the server can't be reached.
 */
final class ShellCache {
    private ShellCache() { }

    static WebResourceResponse fetch(Context ctx, String url, String path, Map<String, String> headers) {
        File dir = new File(ctx.getFilesDir(), "shell");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        String key = sha1(path.equals("/index.html") ? "/" : path);
        File body = new File(dir, key);
        File type = new File(dir, key + ".type");
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(5000);
            c.setReadTimeout(15000);
            c.setInstanceFollowRedirects(true);
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) c.setRequestProperty("Cookie", cookie);
            if (headers != null) {
                String lang = headers.get("Accept-Language");
                if (lang != null) c.setRequestProperty("Accept-Language", lang);
            }
            int status = c.getResponseCode();
            if (status != 200) {
                // Not something to keep (or the server is struggling): let the web view do it.
                c.disconnect();
                return status >= 500 ? cached(body, type) : null;
            }
            String mime = c.getContentType() == null ? guess(path) : c.getContentType();
            byte[] bytes = readAll(c.getInputStream());
            write(body, bytes);
            write(type, mime.getBytes("UTF-8"));
            return response(mime, bytes);
        } catch (Exception offline) {
            return cached(body, type);
        }
    }

    private static WebResourceResponse cached(File body, File type) {
        try {
            if (!body.exists()) return null;
            String mime = type.exists() ? new String(readAll(new FileInputStream(type)), "UTF-8") : "application/octet-stream";
            return response(mime, readAll(new FileInputStream(body)));
        } catch (Exception e) {
            return null;
        }
    }

    private static WebResourceResponse response(String contentType, byte[] bytes) {
        String mime = contentType;
        String charset = null;
        int semi = contentType.indexOf(';');
        if (semi >= 0) {
            mime = contentType.substring(0, semi).trim();
            int cs = contentType.toLowerCase().indexOf("charset=");
            if (cs >= 0) charset = contentType.substring(cs + 8).trim();
        }
        WebResourceResponse r = new WebResourceResponse(mime, charset, new ByteArrayInputStream(bytes));
        Map<String, String> h = new HashMap<>();
        h.put("Cache-Control", "no-cache");
        r.setResponseHeaders(h);
        r.setStatusCodeAndReasonPhrase(200, "OK");
        return r;
    }

    private static String guess(String path) {
        if (path.endsWith(".js")) return "text/javascript";
        if (path.endsWith(".css")) return "text/css";
        if (path.endsWith(".svg")) return "image/svg+xml";
        if (path.endsWith(".woff2")) return "font/woff2";
        if (path.endsWith(".png")) return "image/png";
        if (path.endsWith(".webmanifest")) return "application/manifest+json";
        return "text/html; charset=utf-8";
    }

    private static byte[] readAll(InputStream in) throws Exception {
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        } finally {
            in.close();
        }
    }

    private static void write(File f, byte[] bytes) throws Exception {
        File tmp = new File(f.getPath() + ".tmp");
        FileOutputStream out = new FileOutputStream(tmp);
        try { out.write(bytes); } finally { out.close(); }
        //noinspection ResultOfMethodCallIgnored
        tmp.renameTo(f);
    }

    private static String sha1(String s) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-1").digest(s.getBytes("UTF-8"));
            StringBuilder b = new StringBuilder();
            for (byte x : d) b.append(String.format("%02x", x));
            return b.toString();
        } catch (Exception e) {
            return Integer.toHexString(s.hashCode());
        }
    }
}
