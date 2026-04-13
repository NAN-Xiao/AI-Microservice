package com.ai.gateway.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 动态路由配置属性
 * <p>
 * 绑定 application.yml 中 gateway.dynamic-route.* 节点，
 * 指定从 Nacos Config 中哪个 dataId / group 读取路由规则。
 */
@ConfigurationProperties(prefix = "gateway.dynamic-route")
public class DynamicRouteProperties {

    /** Nacos Config 中存放路由 JSON 的 Data ID，默认 gateway-routes.json */
    private String dataId = "gateway-routes.json";

    /** Nacos Config 的 Group，默认 DEFAULT_GROUP */
    private String group = "DEFAULT_GROUP";

    /** 拉取配置的超时时间（毫秒），默认 5000 */
    private long timeoutMs = 5000L;

    public String getDataId() {
        return dataId;
    }

    public void setDataId(String dataId) {
        this.dataId = dataId;
    }

    public String getGroup() {
        return group;
    }

    public void setGroup(String group) {
        this.group = group;
    }

    public long getTimeoutMs() {
        return timeoutMs;
    }

    public void setTimeoutMs(long timeoutMs) {
        this.timeoutMs = timeoutMs;
    }
}
