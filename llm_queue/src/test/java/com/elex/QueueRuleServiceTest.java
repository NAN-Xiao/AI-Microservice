package com.elex;

import com.elex.config.LlmQueueProperties;
import com.elex.service.QueueRuleService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class QueueRuleServiceTest {
    @Test
    void shouldQueueWhenPathMatchesConfiguredPath() {
        LlmQueueProperties properties = new LlmQueueProperties();
        properties.setQueuedPaths(List.of("/prompt"));
        QueueRuleService service = new QueueRuleService(properties);
        service.updateRules(properties.getQueuedPaths());

        assertTrue(service.shouldQueue("/prompt"));
        assertTrue(service.shouldQueue("/prompt/"));
        assertFalse(service.shouldQueue("/upload/image"));
        assertFalse(service.shouldQueue("/history/abc"));
    }

    @Test
    void shouldUseLatestPropertyValues() {
        LlmQueueProperties properties = new LlmQueueProperties();
        QueueRuleService service = new QueueRuleService(properties);

        properties.setQueuedPaths(List.of("/prompt"));
        service.updateRules(properties.getQueuedPaths());
        assertTrue(service.shouldQueue("/prompt"));
        assertFalse(service.shouldQueue("/upload/image"));

        properties.setQueuedPaths(List.of("/upload/image"));
        service.updateRules(properties.getQueuedPaths());
        assertFalse(service.shouldQueue("/prompt"));
        assertTrue(service.shouldQueue("/upload/image"));
        assertTrue(service.shouldQueue("/upload/image/"));
        assertFalse(service.shouldQueue("/upload/other"));
    }
}
