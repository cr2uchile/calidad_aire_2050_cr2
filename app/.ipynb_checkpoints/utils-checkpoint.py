import pandas as pd
import pandas_gbq
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pydeck as pdk

colores = [['rgb(31, 119, 180)', 'rgba(31, 119, 180, 0.2)'],
 ['rgb(255, 127, 14)', 'rgba(255, 127, 14, 0.2)'],
 ['rgb(44, 160, 44)', 'rgba(44, 160, 44, 0.2)'],
 ['rgb(214, 39, 40)', 'rgba(214, 39, 40, 0.2)'],
 ['rgb(148, 103, 189)', 'rgba(148, 103, 189, 0.2)'],
 ['rgb(140, 86, 75)', 'rgba(140, 86, 75, 0.2)'],
 ['rgb(227, 119, 194)', 'rgba(227, 119, 194, 0.2)'],
 ['rgb(127, 127, 127)', 'rgba(127, 127, 127, 0.2)'],
 ['rgb(188, 189, 34)', 'rgba(188, 189, 34, 0.2)'],
 ['rgb(23, 190, 207)', 'rgba(23, 190, 207, 0.2)']]

mapbox_key = 'pk.eyJ1IjoicGlwc2FsYXMiLCJhIjoiY2thZmliY2kyMDBtazJybzM2b2xwMnpmcSJ9.pvkr8G0WB8vQLWkOZFwonQ'

TEMPLATE = "plotly_white"

COLOR_MAP = {"default": "#262730",
             "pink": "#E22A5B",
             "purple": "#985FFF",}

#factor_escala_emisiones = 3600*4*10**6 AL FINAL ESCALÉ DESDE BQ

# 3. MAPAS
@st.cache
def cargamos_raster(date_inicio = "2015-05-03", date_fin = "2015-05-04",):
    query = f'''
    WITH  base_agrupada as(
        SELECT con.Time, con.lat, con.lon, con.comuna, con.region,
                con.PM25 as concentracion_pm25, emi.EMI_PM25 as emision_pm25
        FROM CR2.concentraciones_PM25_w_geo as con
        JOIN CR2.emisiones_PM25_w_geo as emi
            ON con.lat=emi.lat AND con.lon=emi.lon AND con.Time=emi.Time
        WHERE con.Time>='{date_inicio}' AND con.Time<'{date_fin}'
    )
    SELECT lat, lon, comuna, AVG(emision_pm25) as emision_pm25 , AVG(concentracion_pm25) as concentracion_pm25 ,
    FROM base_agrupada
    GROUP BY lat, lon, comuna
    
'''
    
    #
    df = pandas_gbq.read_gbq(query,
                             project_id='spike-sandbox',
                             use_bqstorage_api=True)
    return df


def plot_mapa(df,width_figuras=1000):
    
    emisiones_comunales = df.groupby('comuna')[['lat','lon','emision_pm25']]\
                            .agg({'lat':'mean', 'lon':'mean','emision_pm25':'sum'}).reset_index()
    df2 = df[['lat','lon','concentracion_pm25']].copy()
    emisiones_comunales['emision_pm25'] *= 1e3
    df2['concentracion_pm25'] *= 1e14
    
    emisiones = pdk.Layer("ColumnLayer",
                             data=emisiones_comunales,
                             get_position=["lon", "lat"],
                             get_elevation="emision_pm25",
                             elevation_scale=800,
                             radius=2000,
                             get_fill_color=["emision_pm25", "emision_pm25", "emision_pm25", 140],
                             pickable=True,
                             auto_highlight=True,)


    concentraciones = pdk.Layer("HeatmapLayer",
                             data=df2,
                             opacity=0.3,
                             get_position=["lon", "lat"],
                             aggregation='"SUM"',
                             threshold=0.05,
                             #color_range=COLOR_BREWER_BLUE_SCALE,
                             get_weight="concentracion_pm25",
                             pickable=True,)

    view_state = pdk.ViewState(longitude=df2.lon.mean(),
                               latitude=df2.lat.mean(),
                               zoom=5,
                               min_zoom=4,
                               max_zoom=10,
                               pitch=40.5,
                               bearing=-90)

    st.pydeck_chart(pdk.Deck(layers=[emisiones, concentraciones],
                             initial_view_state=view_state,
                             map_style="mapbox://styles/mapbox/light-v9",
                             mapbox_key=mapbox_key,
                             height=1000, width=width_figuras))
    
    texto('''Mapa de concentración (colores) y emisión (barras) de MP<sub>2,5</sub>. Mientras la concentración [μg/m<sup>3</sup>] corresponde al promedio para el intervalo de tiempo, la emisión corresponde al valor acumulado (suma) para el mismo intervalo de tiempo [ton/periodo]''')
    
    
    

# 2. SERIES DE TIEMPO
@st.cache
def cargamos_serie_semanal():
    query = '''
    WITH  base_comunal_concentracion as(
        SELECT Time, comuna, region, AVG(PM25) as concentracion_pm25 --promediamos la concentración por comuna por hora
        FROM CR2.concentraciones_PM25_w_geo
        GROUP BY Time, comuna, region
    ),
    base_comunal_emision as(
        SELECT Time, comuna, region, SUM(EMI_PM25) as emision_pm25 --las emisiones las sumamos
        FROM CR2.emisiones_PM25_w_geo
        GROUP BY Time, comuna, region
    ),
    base_agrupada as(
        SELECT con.*, emi.emision_pm25
        FROM base_comunal_concentracion as con
        JOIN base_comunal_emision as emi
            ON con.comuna=emi.comuna AND con.Time=emi.Time
        WHERE con.region!="Zona sin demarcar"
    )
    SELECT EXTRACT(DAYOFWEEK from Time) as day, comuna, region,
           AVG(emision_pm25) as avg_emisionpm25, STDDEV(emision_pm25) as stddev_emisionpm25, 
           AVG(concentracion_pm25) as avg_concentracionpm25, STDDEV(concentracion_pm25) as stddev_concentracionpm25
    FROM base_agrupada
    GROUP BY day, comuna, region
    '''
    #
    df = pandas_gbq.read_gbq(query,
                             project_id='spike-sandbox',
                             use_bqstorage_api=True)
    return df


def plot_weekly_curves(df : pd.DataFrame,
                       resolucion = 'Todas las regiones',
                       tipo = 'emision', 
                       show_shade_fill=True,
                       leyenda_h=True,
                       leyenda_arriba=True,
                       width_figuras=1000):
    
    _df, col_a_mirar = filtrar_serie_daily_por_resolucion(df, resolucion, temporal = 'day')

    fig = go.Figure()
    x = list(df.sort_values(by='day').day.unique())
    x_rev = x[::-1]

    y, y_upper, y_lower = {}, {}, {}
    k = 0
    if tipo == 'emision':
        columnas = ['avg_emisionpm25', 'stddev_emisionpm25']
        yaxis_title = 'Emisión promedio [ton/hr]'
        descripcion = '''Evolución semanal promedio de emisión de MP<sub>2,5</sub> por región/comuna. La linea continua indica el valor promedio y el área achurada (correspondiente a una desviación estandar) representa una medida de la dispersión en torno a este promedio.'''
        
    elif tipo == 'concentracion':
        columnas = ['avg_concentracionpm25', 'stddev_concentracionpm25']
        yaxis_title = 'Concentración promedio [μg/m³]'
        descripcion = '''Evolución semanal promedio de la concentración de MP<sub>2,5</sub> por región/comuna. La linea continua indica el valor promedio y el área achurada (correspondiente a una desviación estandar) representa una medida de la dispersión en torno a este promedio.'''
    
    for comuna in _df[col_a_mirar].unique():
        
        if col_a_mirar == 'comuna':
            aux = _df.query('comuna==@comuna').copy()
        else:
            aux = _df.query('region==@comuna').copy()
        y[comuna] = list(aux[columnas[0]].values)
        y_upper[comuna] = list(y[comuna] + aux[columnas[1]].values)
        y_lower[comuna] = list(y[comuna] - aux[columnas[1]].values)
        y_lower[comuna] = y_lower[comuna][::-1]

        color = colores[k%len(colores)]
        k+=1
        if show_shade_fill:
            fig.add_trace(go.Scatter(x=x+x_rev,
                                    y=y_upper[comuna]+y_lower[comuna],
                                    fill='toself',
                                    fillcolor=f'{color[1]}',
                                    line_color=f'rgba(255,255,255,0)',
                                    showlegend=False,
                                    name=comuna,
                                    ))

        fig.add_trace(go.Scatter(x=x, y=y[comuna],
                                line_color=f'{color[0]}',
                                name=comuna,
                                ))


    fig.update_traces(mode='lines')
    fig.update_layout(height=600, width=width_figuras,
                      yaxis=dict(title=yaxis_title),
                      xaxis = dict(tickmode = 'array',
                                   tickvals = [1,2,3,4,5,6,7],
                                   ticktext = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']),
                      legend_title_text=col_a_mirar,
                      template=TEMPLATE)
    set_leyenda(fig, leyenda_h, leyenda_arriba)

    st.plotly_chart(fig)
    texto(descripcion)



@st.cache
def cargamos_serie_24hrs():
    query = '''
    WITH  base_comunal_concentracion as(
        SELECT Time, comuna, region, AVG(PM25) as concentracion_pm25 --promediamos la concentración por comuna por hora
        FROM CR2.concentraciones_PM25_w_geo
        GROUP BY Time, comuna, region
    ),
    base_comunal_emision as(
        SELECT Time, comuna, region, SUM(EMI_PM25) as emision_pm25 --las emisiones las sumamos
        FROM CR2.emisiones_PM25_w_geo
        GROUP BY Time, comuna, region
    ),
    base_agrupada as(
        SELECT con.*, emi.emision_pm25
        FROM base_comunal_concentracion as con
        JOIN base_comunal_emision as emi
            ON con.comuna=emi.comuna AND con.Time=emi.Time
        WHERE con.region!="Zona sin demarcar"
    )
    SELECT EXTRACT(HOUR from Time) as hora, comuna, region,
    AVG(emision_pm25) as avg_emisionpm25, STDDEV(emision_pm25) as stddev_emisionpm25,
    AVG(concentracion_pm25) as avg_concentracionpm25, STDDEV(concentracion_pm25) as stddev_concentracionpm25
    FROM base_agrupada
    GROUP BY hora, comuna, region
    '''
    
    df = pandas_gbq.read_gbq(query,
                             project_id='spike-sandbox',
                             use_bqstorage_api=True)
    return df

def filtrar_serie_daily_por_resolucion(df, resolucion, temporal = 'hora'):
    if resolucion == 'Todas las regiones':
        _df = df.groupby(['region',temporal])[['avg_emisionpm25', 'avg_concentracionpm25',
                                            'stddev_emisionpm25', 'stddev_concentracionpm25']].mean().reset_index().copy()
        col_a_mirar = 'region'
        
    elif resolucion == 'Todas las comunas':
        _df = df.copy()
        col_a_mirar = 'comuna'
        
    else:
        _df = df.query('region==@resolucion')
        col_a_mirar = 'comuna'
        
    _df = simplificar_nombre_region(_df)
    return _df, col_a_mirar



def plot_daily_curves(df : pd.DataFrame,
                      resolucion = 'Todas las regiones',
                      tipo : str = 'emision',
                      show_shade_fill=True,
                      showlegend=True,
                      leyenda_h=True,
                      leyenda_arriba=True,
                      width_figuras=1000):

    _df, col_a_mirar = filtrar_serie_daily_por_resolucion(df, resolucion)

    fig = go.Figure()
    x = list(_df.hora.unique())
    x_rev = x[::-1]
    y, y_upper, y_lower = {}, {}, {}
    k = 0 #parche para ir cambiando de color
    if tipo == 'emision':
        columnas = ['avg_emisionpm25', 'stddev_emisionpm25']
        yaxis_title = 'Emisión promedio [ton/hr]' 
        descripcion = '''Evolución diaria promedio de emisión de MP<sub/>2,5</sub> por región/comuna. La linea continua indica el valor promedio y el área achurada (correspondiente a una desviacion estandar) representa una medida de la dispersion en torno a este promedio'''

    elif tipo == 'concentracion':
        columnas = ['avg_concentracionpm25', 'stddev_concentracionpm25']
        yaxis_title = 'Concentración promedio de PM25 [μg/m³]'
        descripcion = '''Evolución diaria promedio de la concentración de MP<sub/>2,5</sub> por región/comuna. La linea continua indica el valor promedio y el area achurada (correspondiente a una desviación estandar) representa una medida de la dispersión en torno a este promedio.'''
    
    for comuna in _df[col_a_mirar].unique():
        
        if col_a_mirar == 'comuna':
            aux = _df.query('comuna==@comuna').copy()
        else:
            aux = _df.query('region==@comuna').copy()
            
        y[comuna] = list(aux[columnas[0]].values)
        y_upper[comuna] = list(y[comuna] + 1*aux[columnas[1]].values)
        y_lower[comuna] = list(y[comuna] - 1*aux[columnas[1]].values)
        y_lower[comuna] = y_lower[comuna][::-1]

        color = colores[k%len(colores)] #truquini
        k+=1
        if show_shade_fill:
            fig.add_trace(go.Scatter(x=x+x_rev,
                                    y=y_upper[comuna]+y_lower[comuna],
                                    fill='toself',
                                    fillcolor=f'{color[1]}',
                                    line_color=f'rgba(255,255,255,0)',#borde blanqueli
                                    showlegend=showlegend,
                                    name=comuna,
                                    ))

        fig.add_trace(go.Scatter(x=x, y=y[comuna],
                                line_color=f'{color[0]}',
                                name=comuna,
                                ))


    fig.update_traces(mode='lines')
    fig.update_layout(height=600, width=width_figuras,
                      yaxis_title=yaxis_title,
                      xaxis = dict(tickmode = 'array',
                                   tickvals = [0, 4, 8, 12, 16, 20],
                                   ticktext = ['0 hrs', '4 hrs', '8 hrs', '12 hrs', '16 hrs', '20 hrs']),
                      legend_title_text=col_a_mirar,
                      template=TEMPLATE)
    set_leyenda(fig, leyenda_h, leyenda_arriba)
    st.plotly_chart(fig)
    
    texto(descripcion)




@st.cache
def cargamos_series_tiempo_completas(hourly=False):
    if not hourly:
        query = '''
            WITH base_concentracion as(
                SELECT comuna, region, date, AVG(PM25) as concentracion_pm25 
                FROM CR2.concentraciones_PM25_w_geo
                GROUP BY comuna, region, date
            ),
            base_emision as (
                SELECT comuna, region, date, SUM(EMI_PM25) as emision_pm25 
                FROM CR2.emisiones_PM25_w_geo
                GROUP BY comuna, region, date
            )
            SELECT con.*, emi.emision_pm25
            FROM
            base_concentracion as con
            JOIN
            base_emision as emi
                ON con.comuna=emi.comuna AND con.date=emi.date
            WHERE con.region!="Zona sin demarcar"
            '''
    else:
        query = '''
            WITH base_concentracion as(
                SELECT comuna, region, Time, AVG(PM25) as concentracion_pm25 
                FROM CR2.concentraciones_PM25_w_geo
                GROUP BY comuna, region, Time
            ),
            base_emision as (
                SELECT comuna, region, Time, SUM(EMI_PM25) as emision_pm25 
                FROM CR2.emisiones_PM25_w_geo
                GROUP BY comuna, region, Time
            )
            SELECT con.*, emi.emision_pm25
            FROM
            base_concentracion as con
            JOIN
            base_emision as emi
                ON con.comuna=emi.comuna AND con.Time=emi.Time
            WHERE con.region!="Zona sin demarcar"
            '''

    df = pandas_gbq.read_gbq(query,
                             project_id='spike-sandbox',
                             use_bqstorage_api=True)
    return df

def filtrar_serie_tiempo_por_resolucion(df, resolucion, hourly=False):
    if resolucion == 'Todas las regiones':
        if not hourly:
            tiempo = 'date'
        else:
            tiempo = 'Time'
        _df = df.groupby(['region',tiempo])[['emision_pm25', 'concentracion_pm25']].mean().reset_index().copy()
        col_a_mirar = 'region'
        
    elif resolucion == 'Todas las comunas':
        _df = df.copy()
        col_a_mirar = 'comuna'
        
    else:
        _df = df.query('region==@resolucion')
        col_a_mirar = 'comuna'
        
    _df = simplificar_nombre_region(_df)
    return _df, col_a_mirar


def line_plot(df, y='concentracion_pm25', 
              resolucion='Todas las regiones', 
              leyenda_h=True, 
              hourly=False, 
              leyenda_arriba=True,
              width_figuras=1000):
    
    
    _df, col_a_mirar = filtrar_serie_tiempo_por_resolucion(df, resolucion, hourly=hourly)
    if not hourly:
        sort_time = 'date'
    else:
        sort_time = 'Time'
            
    if y == 'concentracion_pm25':
        ylabel = 'Concentración [μg/m³]'
        descripcion = '''Serie de tiempo de concentración promedio diaria/horaria [μg/m<sup>3</sup>] por región/comuna. El valor promedio de cada día/hora corresponde al promedio de ese dia/hora de los años 2015 a 2017 simulados por el sistema de modelacion WRF-CHIMERE.'''
    else:
        ylabel = 'Emisión [ton/hr]'
        descripcion = '''Serie de tiempo de emisión acumulada diaria/horaria [ton/dia o ton/hr] por región/comuna. El valor promedio de cada día/hora corresponde al promedio de ese dia/hora de los años 2015 a 2017 simulados por el sistema de modelacion WRF-CHIMERE.'''

    fig = px.line(_df.sort_values(by=sort_time),
                  x=sort_time, y=y, 
                  line_group=col_a_mirar,
                  color=col_a_mirar,
                  hover_name=col_a_mirar)

        
    fig.update_layout(height=500, width=width_figuras,
                      xaxis_title="", 
                      yaxis_title=ylabel,
                      template=TEMPLATE)
    
    set_leyenda(fig, leyenda_h, leyenda_arriba)
    st.plotly_chart(fig)
    texto(descripcion, nfont=16)
    
    
def set_leyenda(fig, leyenda_h, leyenda_arriba):
    if leyenda_h:
        fig.layout.update(legend_orientation="h")
    if leyenda_h and leyenda_arriba:
        fig.layout.update(legend=dict(x=-0.1, y=1.2))
    elif leyenda_h and not leyenda_arriba:
        fig.layout.update(legend=dict(x=-0.1, y=-0.1))

    
def get_resolucion(key='resolucion'):    
    lista_regiones = ['Todas las regiones',
                      'Región de Coquimbo',
                      'Región de Valparaíso',
                      'Región Metropolitana de Santiago',
                      "Región del Libertador Bernardo O'Higgins",
                      'Región del Maule', 
                      'Región de Ñuble',
                      'Región del Bío-Bío',
                      'Región de La Araucanía',
                      'Región de Los Ríos',
                      'Región de Los Lagos', 
                      'Región de Aysén del Gral.Ibañez del Campo',
                      'Región de Magallanes y Antártica Chilena',]
                      #'Todas las comunas']
        
    resolucion = st.sidebar.selectbox('Seleccione la/las región/es de interés', lista_regiones, key=key)
    return resolucion




# 1. VISTA GENERAL
def plot_dispersion(df, resolucion, width_figuras=1000, log_scale=True):
    

    _df, col_a_mirar = filtrar_por_resolucion(df, resolucion)
    _df['log número de habitantes'] = np.log(_df['número de habitantes'])
    _df['emision_pm25'] = np.round(_df['emision_pm25'],4)
    _df['concentracion_pm25'] = np.round(_df['concentracion_pm25'],2)
    if log_scale:
        color = 'log número de habitantes'
    else:
        color = 'número de habitantes'
    
    x = "emision_pm25"
    y = "concentracion_pm25"
    hover_data = {'emision_pm25':':.2f'}
    fig = px.scatter(_df, x=x, y=y,
                     color=color, 
                     size='número de habitantes',
                     #hover_data=hover_data,
                     hover_name=col_a_mirar,)
    
    
    fig.update_layout(height=500, width=width_figuras,
                     xaxis_title='Emisión [ton/hr]',
                     yaxis_title='Concentración [μg/m³]',
                     template=TEMPLATE)
    set_leyenda(fig, leyenda_h=True, leyenda_arriba=True)
    st.plotly_chart(fig)
    texto('''Gráfico de dispersión que ilustra la emisión acumulada diaria [ton/día] y la concentración promedio diaria [μg/m<sup>3</sup>] por región/comuna. Ambos parametros representan la condición promedio invernal (mayo-agosto) del periodo 2015 a 2017 simulados por el sistema de modelacion WRF-CHIMERE. El tamaño y color de cada circulo ilustran el número de habitantes por región/comuna. ''')



def ploteamos_barras(df, resolucion, variables=['concentracion_pm25','emision_pm25'], width_figuras=1000):
    
    _df, col_a_mirar = filtrar_por_resolucion(df, resolucion)
    
    var1 = variables[0]
    var2 = variables[1]
    _df.sort_values(by=var1, ascending=False, inplace=True)
    ylabels = {'concentracion_pm25':'Concentración [μg/m³]',
              'emision_pm25':'Emisión [ton/hr]',
              'número de habitantes':'número de habitantes'}
    
    colores_barras = {'concentracion_pm25':'rgb(250, 50, 50)',
              'emision_pm25':'rgb(128, 128, 128)',
              'número de habitantes':'rgb(51, 190, 255)'}
    
    
    # ploteamos
    trace0 = go.Bar(x=_df[col_a_mirar] , y= _df[var1], name=var1 ,marker_color=colores_barras[var1]) 
    trace1 = go.Bar(x=_df[col_a_mirar] , y=[0],showlegend=False,hoverinfo='none' ,marker_color=colores_barras[var1])
    trace2 = go.Bar(x=_df[col_a_mirar] , y=[0], yaxis='y2',showlegend=False,hoverinfo='none', marker_color=colores_barras[var2]) 
    trace3 = go.Bar(x=_df[col_a_mirar] , y=_df[var2], yaxis='y2', name=var2, marker_color=colores_barras[var2])

    data = [trace0,trace1,trace2,trace3]
    
    layout = go.Layout(barmode='group',
                       legend=dict(x=0, y=1.1,orientation="h"),
                       yaxis=dict(title=ylabels[var1]),
                       yaxis2=dict(title = ylabels[var2],
                                   overlaying = 'y',
                                   side='right'))
    fig = go.Figure(data=data, layout=layout)
    fig.update_layout(template=TEMPLATE)
    fig.update_layout(height=500, width=width_figuras,)
    st.plotly_chart(fig)
    texto('''Gráfico de barras que ilustra la emisión acumulada diaria [ton/día] y la concentración promedio diaria [μg/m<sup>3</sup>] por región/comuna. Ambos parametros representan la condición promedio invernal (mayo-agosto) del periodo 2015 a 2017 simulados por el sistema de modelación WRF-CHIMERE.''')
    

    
def simplificar_nombre_region(df):
    diccionario_regiones = {'Región de Coquimbo': 'Coquimbo' ,
                      'Región de Valparaíso': 'Valparaíso' ,
                      'Región Metropolitana de Santiago': 'Metropolitana' ,
                      "Región del Libertador Bernardo O'Higgins": "Lib B O'Higgins" ,
                      'Región del Maule': 'Maule', 
                      'Región de Ñuble': 'Ñuble' ,
                      'Región del Bío-Bío': 'Bío-Bío' ,
                      'Región de La Araucanía': 'La Araucanía' ,
                      'Región de Los Ríos': 'Los Ríos' ,
                      'Región de Los Lagos': 'Los Lagos', 
                      'Región de Aysén del Gral.Ibañez del Campo': 'Aysén' ,
                      'Región de Magallanes y Antártica Chilena': 'Magallanes'}
    return df.replace(diccionario_regiones).copy()
    
def filtrar_por_resolucion(df, resolucion, sort=True):
    if resolucion == 'Todas las regiones':
        _df = df.groupby('region')[['emision_pm25', 'concentracion_pm25','número de habitantes']]\
                .agg({'emision_pm25':'mean', 'concentracion_pm25':'mean','número de habitantes':'sum'}).reset_index().copy()
        col_a_mirar = 'region'
        
    elif resolucion == 'Todas las comunas':
        _df = df.copy()
        col_a_mirar = 'comuna'
        
    else:
        _df = df.query('region==@resolucion')
        col_a_mirar = 'comuna'
        
    _df = simplificar_nombre_region(_df)
    if sort:
        _df.sort_values(by='concentracion_pm25', inplace=True, ascending=False)
    return _df, col_a_mirar

@st.cache
def cargamos_datos_resumen():
    query = '''
    WITH  base_comunal_concentracion as(
        SELECT Time, comuna, region, AVG(PM25) as concentracion_pm25 --promediamos la concentración por comuna por hora
        FROM CR2.concentraciones_PM25_w_geo
        GROUP BY Time, comuna, region
    ),
    base_comunal_emision as(
        SELECT Time, comuna, region, SUM(EMI_PM25) as emision_pm25 --las emisiones las sumamos
        FROM CR2.emisiones_PM25_w_geo
        GROUP BY Time, comuna, region
    ),
    base_agrupada as(
        SELECT con.*, emi.emision_pm25,
        FROM base_comunal_concentracion as con
        JOIN base_comunal_emision as emi
            ON con.comuna=emi.comuna AND con.Time=emi.Time
        WHERE con.region!="Zona sin demarcar"
    ),
    base_agregada as(
    SELECT comuna, region, AVG(emision_pm25) as emision_pm25, AVG(concentracion_pm25) as concentracion_pm25,
    FROM base_agrupada
    GROUP BY comuna, region
    ),
    base_agregada_habitantes as(
    SELECT pm25.*, habitantes.* EXCEPT(comuna, region, cod_comuna)
    FROM base_agregada as pm25
    JOIN CR2.habitantes_por_comuna as habitantes
        ON pm25.comuna=habitantes.comuna
    )
    SELECT * FROM base_agregada_habitantes
    
    '''
#
    df = pandas_gbq.read_gbq(query,
                             project_id='spike-sandbox',
                             use_bqstorage_api=True)
    df.rename(columns={'personas':'número de habitantes'}, inplace=True)
    return df



# LOGOS
def plot_logo_cr2():
    st.sidebar.markdown(
        "<br>"
        '<div style="text-align: center;">'
        '<a href="http://www.cr2.cl/"> '
        '<img src="https://raw.githubusercontent.com/SpikeLab-CL/calidad_aire_2050_cr2/master/logo/cr2_vismet.png" width=100>'
        " </img>"
        "</a> </div>",
        unsafe_allow_html=True,
    )
    
def plot_logo_spike():
     st.sidebar.markdown(
        "<br>"
        '<div style="text-align: center;">'
        '<a href="http://spikelab.xyz"> '
        '<img src="https://raw.githubusercontent.com/SpikeLab-CL/calidad_aire_2050_cr2/master/logo/logo-grey-transparent.png" width=128>'
        " </img>"
        "</a> </div>",
        unsafe_allow_html=True,
    )


# TEXTO
def texto(texto = 'holi', nfont = 16, color = 'black'):
    st.markdown(
            body=generate_html(
                text=texto,
                color=color,
                font_size=f"{nfont}px",
            ),
            unsafe_allow_html=True,
            )
    

def generate_html(
    text,
    color=COLOR_MAP["default"],
    bold=False,
    font_family=None,
    font_size=None,
    line_height=None,
    tag="div",
):
    if bold:
        text = f"<strong>{text}</strong>"
    css_style = f"color:{color};"
    if font_family:
        css_style += f"font-family:{font_family};"
    if font_size:
        css_style += f"font-size:{font_size};"
    if line_height:
        css_style += f"line-height:{line_height};"

    return f"<{tag} style={css_style}>{text}</{tag}>"

def max_width_(width=1000):
    max_width_str = f"max-width: {width}px;"
    st.markdown(
        f"""
    <style>
    .reportview-container .main .block-container{{
        {max_width_str}
    }}
    </style>    
    """,
        unsafe_allow_html=True,
    )
    
    
    
# def load_diccionario_regiones():
#     diccionario_regiones = {10:'Los Lagos',
#     11:'Aysen',
#     13:'Metropolitana',
#     14:'Los Ríos',
#     16:'Ñuble',
#     4:'Coquimbo',
#     5:'Valparaíso',
#     6:'Libertador BOhiggins',
#     7:'Maule',
#     8:'Biobío',
#     9:'Araucanía'}
#     return diccionario_regiones

# def ploteamos_datos_resumen_separados(df, resolucion, version=''):
#     st.markdown(f'**Gráficos de barra {version}**')    
#     _df, col_a_mirar = filtrar_por_resolucion(df, resolucion)
    
#     # ploteamos
#     fig = make_subplots(rows=2, cols=1,
#                         subplot_titles=("Concentraciones [?]", "Emisiones [?]",))
    
#     fig.add_trace(go.Bar(x=_df[col_a_mirar], y=_df.concentracion_pm25, name='concentración'),
#                   row=1, col=1)
#     fig.add_trace(go.Bar(x=_df[col_a_mirar], y=_df.emision_pm25, name='emisión',),
#                   row=2, col=1)
#     fig.update_layout(height=700, width=900,
#                       legend=dict(x=0, y=1.1,orientation="h"),
#                       template=TEMPLATE)
#     st.plotly_chart(fig, use_container_width=False)
    