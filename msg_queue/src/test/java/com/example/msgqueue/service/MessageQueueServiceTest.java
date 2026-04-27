package com.example.msgqueue.service;

import com.example.msgqueue.config.QueueProperties;
import com.example.msgqueue.exception.QueueBusyException;
import com.example.msgqueue.model.EnqueueRequest;
import com.example.msgqueue.service.MessageQueueService.TaskRoute;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class MessageQueueServiceTest {

    @Test
    void shouldThrowTaskBusyWhenQueueExceedsMaxSize() {
        QueueProperties properties = new QueueProperties();
        properties.setMaxSize(200);
        properties.setWorkerCount(1);
        properties.setLongTaskPathPrefixes(List.of("/task/slow"));

        MessageQueueService service = new MessageQueueService(properties);
        for (int i = 0; i < 200; i++) {
            service.enqueue(newRequest("task.slow", i));
        }

        QueueBusyException ex = assertThrows(QueueBusyException.class, () -> service.enqueue(newRequest("task.slow", 201)));
        assertEquals(QueueBusyException.CODE, ex.getCode());
    }

    @Test
    void shouldRouteQueryTaskToDirectProcess() {
        QueueProperties properties = new QueueProperties();
        properties.setLongTaskPathPrefixes(List.of("/task/slow"));

        MessageQueueService service = new MessageQueueService(properties);
        TaskRoute route = service.routeByPath("/messages/query/user/detail");

        assertEquals(TaskRoute.DIRECT_QUERY, route);
    }

    @Test
    void shouldRouteOnlyWhitelistedLongTaskPathToQueue() {
        QueueProperties properties = new QueueProperties();
        properties.setLongTaskPathPrefixes(List.of("/task/slow", "/report/generate"));

        MessageQueueService service = new MessageQueueService(properties);
        assertEquals(TaskRoute.QUEUE, service.routeByPath("/messages/task/slow"));
        assertEquals(TaskRoute.QUEUE, service.routeByPath("/messages/report/generate/daily"));
        assertEquals(TaskRoute.DIRECT_PROCESS, service.routeByPath("/messages/task/fast"));
    }

    private EnqueueRequest newRequest(String topic, int index) {
        EnqueueRequest request = new EnqueueRequest();
        request.setTopic(topic);
        request.setPayload(Map.of("index", index));
        return request;
    }
}
