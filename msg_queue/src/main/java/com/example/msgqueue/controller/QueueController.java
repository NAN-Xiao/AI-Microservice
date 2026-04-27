package com.example.msgqueue.controller;

import com.example.msgqueue.model.EnqueueRequest;
import com.example.msgqueue.model.EnqueueResponse;
import com.example.msgqueue.model.QueueMessage;
import com.example.msgqueue.model.QueueStatsResponse;
import com.example.msgqueue.service.MessageQueueService;
import com.example.msgqueue.service.MessageQueueService.TaskRoute;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@RestController
public class QueueController {

    private final MessageQueueService queueService;

    public QueueController(MessageQueueService queueService) {
        this.queueService = queueService;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }

    @GetMapping("/queue/stats")
    public QueueStatsResponse stats() {
        return new QueueStatsResponse(
                queueService.queueSize(),
                queueService.processedCount(),
                queueService.failedCount()
        );
    }

    @PostMapping({"/messages", "/messages/**"})
    public ResponseEntity<EnqueueResponse> enqueueByPost(
            @Valid @RequestBody EnqueueRequest request,
            HttpServletRequest servletRequest
    ) {
        return handleEnqueue(request, servletRequest);
    }

    @GetMapping({"/messages", "/messages/**"})
    public ResponseEntity<EnqueueResponse> enqueueByGet(
            @RequestParam Map<String, String> queryParams,
            HttpServletRequest servletRequest
    ) {
        EnqueueRequest request = new EnqueueRequest();
        request.setTopic(queryParams.getOrDefault("topic", "default"));

        Map<String, Object> payload = new HashMap<>();
        for (Map.Entry<String, String> entry : queryParams.entrySet()) {
            if (!"topic".equalsIgnoreCase(entry.getKey())) {
                payload.put(entry.getKey(), entry.getValue());
            }
        }
        request.setPayload(payload);

        return handleEnqueue(request, servletRequest);
    }

    private ResponseEntity<EnqueueResponse> handleEnqueue(
            EnqueueRequest request,
            HttpServletRequest servletRequest
    ) {
        TaskRoute route = queueService.routeByPath(servletRequest.getRequestURI());
        if (route == TaskRoute.QUEUE) {
            QueueMessage message = queueService.enqueue(request);
            EnqueueResponse response = new EnqueueResponse(
                    message.messageId(),
                    "queued",
                    queueService.queueSize()
            );
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
        }

        String taskId = queueService.processDirect(request, route);
        String status = route == TaskRoute.DIRECT_QUERY ? "query-processed" : "processed-directly";
        EnqueueResponse response = new EnqueueResponse(taskId, status, queueService.queueSize());
        return ResponseEntity.ok(response);
    }
}
