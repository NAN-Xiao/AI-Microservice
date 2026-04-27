package com.example.msgqueue.model;

import jakarta.validation.constraints.NotNull;

import java.util.Map;

public class EnqueueRequest {

    private String topic = "default";

    @NotNull
    private Map<String, Object> payload;

    public String getTopic() {
        if (topic == null || topic.isBlank()) {
            return "default";
        }
        return topic;
    }

    public void setTopic(String topic) {
        this.topic = topic;
    }

    public Map<String, Object> getPayload() {
        return payload;
    }

    public void setPayload(Map<String, Object> payload) {
        this.payload = payload;
    }
}

