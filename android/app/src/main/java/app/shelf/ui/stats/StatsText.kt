package app.shelf.ui.stats

import java.text.NumberFormat

/** Time listened in words: minutes up to two hours, then hours. */
fun hoursText(minutes: Int): String =
    if (minutes >= 120) "${NumberFormat.getIntegerInstance(java.util.Locale.US).format(Math.round(minutes / 60.0))} hours"
    else if (minutes == 1) "1 minute" else "$minutes minutes"

/** What kind of listener the hours say (as on the web): (short, with the reason). */
fun listenerKind(hours: List<Int>): Pair<String, String> {
    val total = hours.sum().coerceAtLeast(1).toDouble()
    val at = { from: Int, to: Int -> hours.subList(from, to).sum() }
    if ((at(22, 24) + at(0, 4)) / total > 0.3) return "a night owl" to "a night owl: a lot of your listening happens after 10 pm"
    if (at(5, 10) / total > 0.3) return "an early bird" to "an early bird: a lot of your listening happens before 10 am"
    val peak = hours.indexOf(hours.max())
    val time = when { peak == 0 -> "midnight"; peak == 12 -> "noon"; peak < 12 -> "$peak am"; else -> "${peak - 12} pm" }
    return "most often listening around $time".let { it to it }
}

/** The streak sentence for a period ("month", "year", "all" or a year). */
fun streakText(current: Int, longest: Int, period: String): String {
    val now = when { current > 1 -> "You’ve listened $current days in a row."; current == 1 -> "You’ve listened today."; else -> "No streak going right now." }
    val where = when (period) { "all" -> "ever"; "month" -> "this month"; "year" -> "this year"; else -> "in $period" }
    return if (longest > 1) "$now Your longest run $where: $longest days." else now
}

val PERIOD_LABEL = mapOf("month" to "This month", "year" to "This year", "all" to "All time")
