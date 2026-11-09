package app.shelf.data

/** The list with the item at `from` moved to `to` (dragging a song in a playlist). */
fun <T> moveItem(list: List<T>, from: Int, to: Int): List<T> {
    if (from !in list.indices || to !in list.indices || from == to) return list
    return list.toMutableList().apply { add(to, removeAt(from)) }
}
