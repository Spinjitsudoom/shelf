package app.shelf.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import app.shelf.R

private fun archivo(weight: Int, width: Float = 100f) = Font(
    R.font.archivo, FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight), FontVariation.width(width)),
)

/** Archivo, the web app's typeface, at its everyday weights. */
val Archivo = FontFamily(archivo(400), archivo(500), archivo(600), archivo(700), archivo(800), archivo(900))

/** Archivo wide and black, for album and page titles (like the web's .album-title). */
val ArchivoDisplay = FontFamily(archivo(900, 125f))

/** Caveat, the hand-writing on mix tape labels. */
val Caveat = FontFamily(
    Font(R.font.caveat, FontWeight.Bold, variationSettings = FontVariation.Settings(FontVariation.weight(700))),
)

val ShelfType = Typography(
    displayLarge = TextStyle(fontFamily = ArchivoDisplay, fontSize = 44.sp, lineHeight = 44.sp, letterSpacing = (-0.025).em),
    displayMedium = TextStyle(fontFamily = ArchivoDisplay, fontSize = 34.sp, lineHeight = 35.sp, letterSpacing = (-0.025).em),
    displaySmall = TextStyle(fontFamily = ArchivoDisplay, fontSize = 26.sp, lineHeight = 27.sp, letterSpacing = (-0.02).em),
    headlineSmall = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.ExtraBold, fontSize = 21.sp, lineHeight = 26.sp),
    titleLarge = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.Bold, fontSize = 19.sp, lineHeight = 24.sp),
    titleMedium = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 21.sp),
    titleSmall = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 19.sp),
    bodyLarge = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.Normal, fontSize = 16.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.Normal, fontSize = 13.sp, lineHeight = 18.sp),
    labelLarge = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.Bold, fontSize = 15.sp, lineHeight = 20.sp),
    labelMedium = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, lineHeight = 17.sp),
    labelSmall = TextStyle(fontFamily = Archivo, fontWeight = FontWeight.SemiBold, fontSize = 11.sp, lineHeight = 14.sp),
)
