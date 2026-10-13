package com.example.controller;

import com.example.service.UserService;
import com.example.model.User;

public class UserController {
    private final UserService<String> service;

    public UserController(UserService<String> service) {
        this.service = service;
    }

    public String show(long id) {
        User user = service.getUser(id, "web");
        return user.getName();
    }
}
