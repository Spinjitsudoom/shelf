package app.shelf.ui.common

/** "3:24" */
fun fmtTime(seconds: Double): String {
    val s = seconds.toInt().coerceAtLeast(0)
    return if (s >= 3600) "%d:%02d:%02d".format(s / 3600, s / 60 % 60, s % 60) else "%d:%02d".format(s / 60, s % 60)
}

/** "2 hr 27 min", "23 min" (like the web app's fmtLength). */
fun fmtLength(seconds: Double): String {
    val m = Math.round(seconds / 60).toInt()
    return if (m >= 60) "${m / 60} hr ${m % 60} min" else "$m min"
}

fun plural(n: Int, word: String) = "$n $word" + if (n == 1) "" else "s"
