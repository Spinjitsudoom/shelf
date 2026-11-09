package app.shelf.update

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdaterTest {
    @Test fun versionCodeFromTag() {
        assertEquals(701, versionCode("v0.7.1"))
        assertEquals(1000, versionCode("0.10.0"))
        assertEquals(700, versionCode("v0.7.0-preview.5"))
        assertEquals(10203, versionCode("V1.2.3"))
        assertEquals(0, versionCode("nonsense"))
    }

    @Test fun picksApkAsset() {
        val rel = Json.parseToJsonElement("""{"tag_name":"v0.7.0","assets":[
            {"name":"Shelf-0.7.0.exe","browser_download_url":"https://x/exe"},
            {"name":"Shelf-0.7.0.apk","browser_download_url":"https://x/apk"},
            {"name":"shelf_0.7.0_amd64.deb","browser_download_url":"https://x/deb"}]}""").jsonObject
        assertEquals("https://x/apk", apkAsset(rel))
        assertNull(apkAsset(Json.parseToJsonElement("""{"assets":[]}""").jsonObject))
    }

    @Test fun rejectsOtherPackageOrOlder() {
        assertTrue(shouldOffer(mine = 700, latest = 701, apkPackage = "app.shelf", apkCode = 701, myPackage = "app.shelf"))
        assertFalse("not newer", shouldOffer(701, 701, "app.shelf", 701, "app.shelf"))
        assertFalse("older", shouldOffer(702, 701, "app.shelf", 701, "app.shelf"))
        assertFalse("another app", shouldOffer(700, 701, "com.evil", 701, "app.shelf"))
        assertFalse("not what the release said", shouldOffer(700, 701, "app.shelf", 700, "app.shelf"))
        assertFalse("not an APK at all", shouldOffer(700, 701, null, null, "app.shelf"))
    }
}
