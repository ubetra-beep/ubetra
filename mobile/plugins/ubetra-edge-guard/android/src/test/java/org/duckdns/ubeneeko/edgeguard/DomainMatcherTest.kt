package org.duckdns.ubeneeko.edgeguard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DomainMatcherTest {
    @Test
    fun normalize_stripsSchemeAndWww() {
        assertEquals("reddit.com", DomainMatcher.normalize("https://www.Reddit.com/r/all"))
        assertEquals("example.org", DomainMatcher.normalize("EXAMPLE.ORG:443"))
    }

    @Test
    fun isBlocked_matchesParents() {
        val blocked = setOf("reddit.com", "x.com")
        assertTrue(DomainMatcher.isBlocked("www.reddit.com", blocked))
        assertTrue(DomainMatcher.isBlocked("old.reddit.com", blocked))
        assertTrue(DomainMatcher.isBlocked("x.com", blocked))
        assertFalse(DomainMatcher.isBlocked("reddit.org", blocked))
        assertFalse(DomainMatcher.isBlocked("notreddit.com", blocked))
    }
}
