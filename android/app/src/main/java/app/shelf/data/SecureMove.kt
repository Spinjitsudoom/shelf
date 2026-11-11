package app.shelf.data

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/*
 * Moving to the server's secure (https) address (see src/shelf/secure.py).
 *
 * On plain http from the internet, passwords and music travel in the clear. When the server has a
 * secure address, the app moves there by itself (the sign-in token works the same there). Songs
 * queued or downloaded before the move keep their old addresses, which is how the player's cache
 * knows them; requests to the old address are sent to the new one instead (rebase), so nothing
 * goes over plain http once moved. At home (a private address) nothing changes.
 */

private val PRIVATE_SUFFIXES = listOf(".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net")

/** At home or on the tailnet: loopback, LAN, Tailscale's 100.64/10, bare names, .local and such. The same rules as secure.py. */
fun isPrivateHost(host: String): Boolean {
    val h = host.lowercase().removePrefix("[").removeSuffix("]").removeSuffix(".")
    val v4 = Regex("^(\\d+)\\.(\\d+)\\.(\\d+)\\.(\\d+)$").find(h)
    if (v4 != null) {
        val a = v4.groupValues[1].toInt()
        val b = v4.groupValues[2].toInt()
        return a == 10 || a == 127 || a == 0 || (a == 172 && b in 16..31) || (a == 192 && b == 168) ||
            (a == 169 && b == 254) || (a == 100 && b in 64..127)
    }
    if (':' in h) return h == "::1" || h.startsWith("fc") || h.startsWith("fd") || Regex("^fe[89ab]").containsMatchIn(h)
    return h == "localhost" || '.' !in h || PRIVATE_SUFFIXES.any { h.endsWith(it) }
}

/** The address to move to, or null to stay where we are. */
fun secureMoveTarget(server: String, secureUrl: String?): String? {
    val to = secureUrl?.trimEnd('/')?.takeIf { it.startsWith("https://") } ?: return null
    val here = "$server/".toHttpUrlOrNull() ?: return null
    val there = "$to/".toHttpUrlOrNull() ?: return null
    if (here.scheme != "http" || isPrivateHost(here.host) || here.host == there.host) return null
    return to
}

/** [url] sent to the current server instead, if it's on an address the app has moved away from. */
fun rebase(url: HttpUrl, former: Set<String>, now: HttpUrl): HttpUrl? {
    val from = former.mapNotNull { "$it/".toHttpUrlOrNull() }
        .firstOrNull { it.scheme == url.scheme && it.host == url.host && it.port == url.port } ?: return null
    if (from.host == now.host && from.port == now.port && from.scheme == now.scheme) return null
    return url.newBuilder().scheme(now.scheme).host(now.host).port(now.port).build()
}
