---
title: My creative side
layout: default
author: Danishjeet Singh
date: 2024-10-04
---

# Miscellaneous

I have some old graphic design mockups, and some pictures I've took in a while and some doodles.

<div class="miscellaneous-list">
  {% for file in site.pages %}
    {% if file.path contains "misc/" %}
      <div class="file-entry">
        <strong><a href="{{ file.url }}" class="file-title">{{ file.title }}</a></strong> - {{ page.date }}
        <p class="file-description">{{ file.description }}</p>
      </div>
    {% endif %}
  {% endfor %}
</div>
 


[Back to home](/)
